"""Regression coverage for fail-closed routing and approval identity."""
import pytest

from app.core.exceptions import AppError
from app.models.user import Role, User
from app.models.workflow import ApprovalRecord, WorkflowInstance
from app.services import workflow_engine as engine
from tests import helpers


def person(uid, role, name="Same name"):
    return User(id=uid, username=f"user{uid}", password_hash="x", real_name=name,
                roles=[Role(code=role, name=role)])


def running(db, *, mode="and", graph=None, current="n1"):
    owner = helpers.make_user(db)
    contract = helpers.make_contract(db, owner_id=owner.id, status="in_approval")
    graph = graph or helpers.approval_graph(nodes=[{
        "id": "n1", "type": "approval", "name": "Approval", "signMode": mode,
        "assignees": ["role:a", "role:b"],
    }])
    definition = helpers.make_definition(db, graph=graph)
    instance = helpers.make_instance(db, definition.id, contract.id, current_node_id=current)
    db.commit()
    return contract, definition, instance


def approve(db, instance, user):
    return engine.act(db, instance, action="approve", operator=user, comment="yes")


def test_condition_enters_selected_approval(db):
    graph = helpers.approval_graph(nodes=[
        {"id": "condition", "type": "condition", "rules": [{"when": "default", "goto": "n1"}]},
        {"id": "n1", "type": "approval", "assignees": ["role:a"]},
    ], edges=[{"from": "start", "to": "condition"}, {"from": "n1", "to": "end"}])
    contract, definition, _ = running(db, graph=graph)
    instance = engine.start_instance(db, definition, contract, 1, "Starter", {})
    assert instance.current_node_id == "n1"
    assert instance.status == "running"
    assert contract.status != "approved"


@pytest.mark.parametrize("graph", [
    {"nodes": [], "edges": []},
    {"nodes": [{"id": "n1", "type": "unknown"}], "edges": [{"from": "start", "to": "n1"}]},
    {"nodes": [{"id": "c", "type": "condition", "rules": [{"when": "default", "goto": "c"}]}],
     "edges": [{"from": "start", "to": "c"}]},
    helpers.approval_graph(nodes=[{"id": "n1", "type": "approval", "assignees": []}]),
])
def test_invalid_start_has_no_committed_instance_or_approval(db, graph):
    contract, definition, existing = running(db, graph=graph)
    before = db.query(WorkflowInstance).count()
    with pytest.raises(AppError):
        engine.start_instance(db, definition, contract, 1, "Starter", {})
    db.commit()  # Even a caller that commits after failure must not persist partial work.
    assert db.query(WorkflowInstance).count() == before
    assert db.query(ApprovalRecord).count() == 0
    assert contract.status == "in_approval"


def test_and_requires_each_role_slot_and_distinct_user_ids(db):
    contract, _, instance = running(db)
    approve(db, instance, person(10, "a"))
    with pytest.raises(AppError):
        approve(db, instance, person(11, "a"))
    assert instance.status == "running"
    approve(db, instance, person(12, "b"))  # same display name still a distinct signer
    assert instance.status == "approved"
    assert contract.status == "approved"


def test_duplicate_user_cannot_consume_another_role_slot(db):
    _, _, instance = running(db)
    user = person(10, "a")
    user.roles.append(Role(code="b", name="b"))
    approve(db, instance, user)
    with pytest.raises(AppError):
        approve(db, instance, user)
    assert instance.status == "running"
    assert db.query(ApprovalRecord).filter_by(instance_id=instance.id, action="approve").count() == 1


def test_sequence_rejects_out_of_order_approval(db):
    _, _, instance = running(db, mode="sequence")
    with pytest.raises(AppError):
        approve(db, instance, person(12, "b"))
    assert db.query(ApprovalRecord).count() == 0
    approve(db, instance, person(10, "a"))
    approve(db, instance, person(12, "b"))
    assert instance.status == "approved"


def test_invalid_later_edge_rolls_back_approval(db):
    graph = helpers.approval_graph(edges=[{"from": "start", "to": "n1"}])
    contract, _, instance = running(db, graph=graph)
    with pytest.raises(AppError):
        approve(db, instance, person(10, "dept_manager"))
    db.commit()
    assert db.query(ApprovalRecord).count() == 0
    assert instance.status == "running"
    assert contract.status == "in_approval"


@pytest.mark.parametrize("action", ["transfer", "countersign"])
def test_unsupported_actions_do_not_claim_success(db, action):
    _, _, instance = running(db)
    with pytest.raises(AppError):
        engine.act(db, instance, action=action, operator=person(10, "a"), comment="")
    assert db.query(ApprovalRecord).count() == 0


API = "/api/v1/workflow"


def definition_payload(**changes):
    payload = {"name": "Flow", "contractTypes": ["purchase"], "nodes": [
        {"id": "n1", "type": "approval", "name": "Review", "assignees": ["role:a"]}]}
    payload.update(changes)
    return payload


def test_definition_update_keeps_running_instances_on_original_graph(client, db):
    original = client.post(f"{API}/definitions", json=definition_payload()).json()
    contract, _, _ = running(db)
    instance = helpers.make_instance(db, original["id"], contract.id, current_node_id="n1")
    db.commit()
    replacement = client.post(f"{API}/definitions", json=definition_payload(
        id=original["id"], name="Changed", nodes=[
            {"id": "new", "type": "approval", "name": "New", "assignees": ["role:b"]}])).json()
    assert replacement["id"] != original["id"]
    assert replacement["version"] == 2
    db.expire_all()
    from app.models.workflow import WorkflowDefinition
    old = db.get(WorkflowDefinition, original["id"])
    assert old.version == 1 and old.graph["nodes"][1]["id"] == "n1"
    assert old.enabled is False
    approve(db, instance, person(10, "a"))
    assert instance.status == "approved"
    assert client.post(f"{API}/definitions/{old.id}/toggle").status_code == 409
    assert client.post(f"{API}/definitions", json=definition_payload(id=old.id)).status_code == 409


@pytest.mark.parametrize("node", [
    {"id": "start", "type": "approval", "name": "Bad", "assignees": ["role:a"]},
    {"id": "bad", "type": "unknown", "name": "Bad"},
    {"id": "bad", "type": "approval", "name": "Bad", "assignees": []},
    {"id": "bad", "type": "approval", "name": "Bad", "assignees": ["a"]},
    {"id": "bad", "type": "approval", "name": "Bad", "assignees": ["role:a"], "signMode": "unknown"},
    {"id": "bad", "type": "condition", "name": "Bad", "riskThreshold": -1},
    {"id": "bad", "type": "condition", "name": "Bad", "amountThreshold": -1},
])
def test_definition_rejects_invalid_nodes(client, db, node):
    response = client.post(f"{API}/definitions", json=definition_payload(nodes=[node]))
    assert response.status_code in {400, 422}


def test_auto_complete_start_preserves_approved_contract(client, db):
    owner = helpers.make_user(db)
    contract = helpers.make_contract(db, owner_id=owner.id, status="review_passed")
    version = helpers.make_version(db, contract.id)
    task = helpers.make_review_task(db, contract.id, version_id=version.id, status="completed")
    helpers.make_report(db, task.id, contract.id)
    helpers.make_definition(db, graph={"nodes": [], "edges": [{"from": "start", "to": "end"}]})
    db.commit()
    response = client.post(f"{API}/instances", json={"contractId": contract.id})
    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    db.expire_all()
    assert contract.status == "approved"


def test_workflow_writes_require_permissions(client, db):
    user = helpers.make_user(db)
    db.commit()
    client.user_state["user_id"] = user.id
    assert client.post(f"{API}/definitions", json=definition_payload()).status_code == 403
    assert client.post(f"{API}/definitions/999/toggle").status_code == 403
    assert client.post(f"{API}/instances", json={"contractId": 999}).status_code == 403
    assert client.post(f"{API}/instances/999/actions", json={"expectedNodeId": "n1", "action": "approve"}).status_code == 403
    assert client.post(f"{API}/instances/999/urge").status_code == 403


def test_workflow_instances_require_contract_scope(client, db):
    owner = helpers.make_user(db, username="owner")
    other = helpers.make_user(db, username="other")
    from app.models.user import Permission
    role = Role(code="outsider", name="outsider", data_scope="self", permissions=[
        Permission(code="workflow:approve", name="approve"),
        Permission(code="workflow:start", name="start")])
    other.roles = [role]
    contract = helpers.make_contract(db, owner_id=owner.id)
    definition = helpers.make_definition(db, graph=helpers.approval_graph())
    instance = helpers.make_instance(db, definition.id, contract.id, starter_id=other.id)
    db.commit()
    client.user_state["user_id"] = other.id
    assert client.get(f"{API}/instances").json() == []
    assert client.get(f"{API}/instances/{instance.id}").status_code == 403
    assert client.post(f"{API}/instances", json={"contractId": contract.id}).status_code == 403
    assert client.post(f"{API}/instances/{instance.id}/actions", json={"expectedNodeId": "n1", "action": "approve"}).status_code == 403
    assert client.post(f"{API}/instances/{instance.id}/withdraw", json={"reason": "x"}).status_code == 403
    assert client.post(f"{API}/instances/{instance.id}/urge").status_code == 403


@pytest.mark.parametrize("graph", [
    {"nodes": [{"id": "c", "type": "condition", "rules": [None]}], "edges": []},
    {"nodes": [], "edges": [{"from": [], "to": "end"}]},
    {"nodes": [{"id": "c", "type": "condition", "rules": [
        {"when": "risk_score / 0 > 1", "goto": "end"}, {"when": "default", "goto": "end"}]}],
     "edges": [{"from": "start", "to": "c"}]},
])
def test_malformed_or_uncomputable_graph_raises_app_error_without_partial_writes(db, graph):
    contract, definition, _ = running(db, graph=graph)
    with pytest.raises(AppError):
        engine.start_instance(db, definition, contract, 1, "Starter", {})
    db.commit()
    assert db.query(WorkflowInstance).count() == 1
    assert db.query(ApprovalRecord).count() == 0
    assert contract.status == "in_approval"



def test_action_requires_expected_node_and_replay_cannot_approve_next_node(client, db):
    graph = helpers.approval_graph(nodes=[
        {"id": "n1", "type": "approval", "assignees": ["role:admin"]},
        {"id": "n2", "type": "approval", "assignees": ["role:admin"]},
    ], edges=[{"from": "start", "to": "n1"}, {"from": "n1", "to": "n2"}, {"from": "n2", "to": "end"}])
    contract, _, instance = running(db, graph=graph)
    endpoint = f"{API}/instances/{instance.id}/actions"
    assert client.post(endpoint, json={"action": "approve"}).status_code == 422
    response = client.post(endpoint, json={"action": "approve", "expectedNodeId": "n1"})
    assert response.status_code == 200
    assert response.json()["currentNodeId"] == "n2"
    assert client.post(endpoint, json={"action": "approve", "expectedNodeId": "n1"}).status_code == 409
    db.expire_all()
    assert contract.status == "in_approval"
    assert instance.current_node_id == "n2"
    assert db.query(ApprovalRecord).filter_by(instance_id=instance.id, action="approve").count() == 1
    assert client.post(endpoint, json={"action": "approve", "expectedNodeId": "n2"}).json()["status"] == "approved"


def test_stale_loaded_instance_checks_expected_node_against_locked_row(db, session_factory):
    contract, _, instance = running(db, graph=helpers.approval_graph(nodes=[
        {"id": "n1", "type": "approval", "assignees": ["role:a"]},
        {"id": "n2", "type": "approval", "assignees": ["role:a"]},
    ], edges=[{"from": "start", "to": "n1"}, {"from": "n1", "to": "n2"}, {"from": "n2", "to": "end"}]))
    with session_factory() as stale_db:
        stale = stale_db.get(WorkflowInstance, instance.id)
        approve(db, instance, person(10, "a"))
        assert stale.current_node_id == "n1"
        with pytest.raises(AppError) as error:
            engine.act(stale_db, stale, action="approve", operator=person(10, "a"),
                       comment="", expected_node_id="n1")
        assert error.value.status_code == 409
    db.expire_all()
    assert instance.current_node_id == "n2"
    assert contract.status == "in_approval"


def test_start_snapshot_includes_contract_type(client, db):
    owner = helpers.make_user(db)
    contract = helpers.make_contract(db, owner_id=owner.id, status="review_passed", contract_type="sales")
    version = helpers.make_version(db, contract.id)
    task = helpers.make_review_task(db, contract.id, version_id=version.id, status="completed")
    helpers.make_report(db, task.id, contract.id)
    definition = helpers.make_definition(db, contract_types=["sales"], graph=helpers.approval_graph(nodes=[
        {"id": "c", "type": "condition", "rules": [
            {"when": "contract_type == 'sales'", "goto": "n1"}, {"when": "default", "goto": "end"}]},
        {"id": "n1", "type": "approval", "assignees": ["role:admin"]},
    ], edges=[{"from": "start", "to": "c"}, {"from": "n1", "to": "end"}]))
    db.commit()
    response = client.post(f"{API}/instances", json={"contractId": contract.id})
    assert response.status_code == 200
    assert response.json()["contextSnapshot"]["contract_type"] == "sales"
    assert response.json()["currentNodeId"] == "n1"


def test_three_definition_versions_keep_lineage_and_select_latest_enabled(client, db):
    first = client.post(f"{API}/definitions", json=definition_payload()).json()
    second = client.post(f"{API}/definitions", json=definition_payload(id=first["id"])).json()
    third = client.post(f"{API}/definitions", json=definition_payload(id=second["id"])).json()
    assert [first["version"], second["version"], third["version"]] == [1, 2, 3]
    for old in [first, second]:
        assert client.post(f"{API}/definitions/{old['id']}/toggle").status_code == 409
    contract, _, _ = running(db)
    selected = engine.pick_definition_for_contract(db, contract)
    assert selected.id == third["id"]
    assert selected.version == 3


def test_return_at_first_approval_fails_closed(db):
    """Return at the first approval node must error and stop; no guessed fallback node (the old impl hard-coded n1 / dept-manager approval)."""
    _, _, instance = running(db)
    with pytest.raises(AppError) as error:
        engine.act(db, instance, action="return", operator=person(10, "a"), comment="")
    assert error.value.status_code == 400
    db.commit()
    assert instance.current_node_id == "n1"
    assert instance.status == "running"


def test_return_lands_on_previous_approval_and_skips_condition_traces(db):
    """The return target is the previous real approval node; a condition-route system flow (a non-approval node) must not be treated as a return target."""
    graph = helpers.approval_graph(nodes=[
        {"id": "boss", "type": "approval", "name": "经理审批", "assignees": ["role:a"]},
        {"id": "c", "type": "condition", "rules": [{"when": "default", "goto": "sec"}]},
        {"id": "sec", "type": "approval", "name": "法务审批", "assignees": ["role:a"]},
    ], edges=[{"from": "start", "to": "boss"}, {"from": "boss", "to": "c"}, {"from": "sec", "to": "end"}])
    contract, definition, instance = running(db, graph=graph, current="boss")
    approve(db, instance, person(10, "a"))
    assert instance.current_node_id == "sec"
    engine.act(db, instance, action="return", operator=person(10, "a"), comment="")
    assert instance.current_node_id == "boss"
    assert instance.current_node_name == "经理审批"
    assert instance.status == "running"
    assert contract.status == "in_approval"


def test_start_approval_rejects_duplicate_running_instance(client, db):
    owner = helpers.make_user(db)
    contract = helpers.make_contract(db, owner_id=owner.id, status="review_passed")
    version = helpers.make_version(db, contract.id)
    task = helpers.make_review_task(db, contract.id, version_id=version.id, status="completed")
    helpers.make_report(db, task.id, contract.id)
    helpers.make_definition(db, graph=helpers.approval_graph())
    db.commit()
    first = client.post(f"{API}/instances", json={"contractId": contract.id})
    assert first.status_code == 200
    second = client.post(f"{API}/instances", json={"contractId": contract.id})
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "WORKFLOW_ALREADY_RUNNING"

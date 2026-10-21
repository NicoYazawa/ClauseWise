"""Unit tests for the services layer (part 3): approval workflow engine."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.core.exceptions import AppError
from app.services import workflow_engine
from tests import helpers


@pytest.fixture()
def wf_env(db):
    user = helpers.make_user(db)
    contract = helpers.make_contract(db, owner_id=user.id, status="review_passed")
    definition = helpers.make_definition(db, graph=helpers.approval_graph())
    db.commit()
    return {"user": user, "contract": contract, "definition": definition}


def _manager_user():
    from app.models.user import Role, User

    role = Role(id=2, code="dept_manager", name="部门经理")
    return User(id=2, username="mgr", password_hash="x", real_name="经理", roles=[role])


class TestWorkflowEngineLookup:
    def test_get_definition_or_404(self, wf_env, db):
        assert workflow_engine.get_definition_or_404(db, wf_env["definition"].id) is not None
        with pytest.raises(AppError) as ei:
            workflow_engine.get_definition_or_404(db, 99999)
        assert ei.value.detail["code"] == "WORKFLOW_DEF_NOT_FOUND"

    def test_get_instance_or_404(self, wf_env, db):
        inst = helpers.make_instance(db, wf_env["definition"].id, wf_env["contract"].id)
        db.commit()
        assert workflow_engine.get_instance_or_404(db, inst.id) is not None
        with pytest.raises(AppError) as ei:
            workflow_engine.get_instance_or_404(db, 99999)
        assert ei.value.detail["code"] == "WORKFLOW_INST_NOT_FOUND"


class TestGraphWalking:
    def test_nodes_edges_empty(self):
        from app.models.workflow import WorkflowDefinition

        with pytest.raises(AppError):
            workflow_engine._nodes_edges(WorkflowDefinition(graph=None))

    def test_next_node_plain(self):
        # _next_node parses from the given node: a non-condition node is returned as-is
        nodes = {"start": {"id": "start"}, "n1": {"id": "n1", "type": "approval", "assignees": ["role:dept_manager"]}}
        edges = {"start": "n1"}
        nid, node = workflow_engine._next_node(nodes, edges, "start", {})
        assert nid == "start"
        assert node["id"] == "start"

    def test_next_node_missing(self):
        nodes, edges = {}, {}
        with pytest.raises(AppError):
            workflow_engine._next_node(nodes, edges, "ghost", {})

    def test_next_node_condition(self):
        nodes = {"c": {"id": "c", "type": "condition",
                       "rules": [{"when": "risk_score < 85", "goto": "low"},
                                 {"when": "default", "goto": "high"}]},
                 "low": {"id": "low"}, "high": {"id": "high"}}
        nid, _ = workflow_engine._next_node(nodes, {}, "c", {"risk_score": 60})
        assert nid == "low"

    def test_next_node_condition_default_branch(self):
        nodes = {"c": {"id": "c", "type": "condition",
                       "rules": [{"when": "risk_score < 85", "goto": "low"},
                                 {"when": "default", "goto": "high"}]},
                 "low": {"id": "low"}, "high": {"id": "high"}}
        nid, _ = workflow_engine._next_node(nodes, {}, "c", {"risk_score": 90})
        assert nid == "high"

    def test_next_node_guard_limit(self):
        # A cycle must fail closed.
        nodes = {"loop": {"id": "loop", "type": "condition", "rules": [{"when": "1", "goto": "loop"}]}}
        with pytest.raises(AppError):
            workflow_engine._next_node(nodes, {}, "loop", {})

    def test_eval_condition_default_only(self):
        node = {"rules": [{"when": "default", "goto": "end"}]}
        assert workflow_engine._eval_condition(node, {}) == "end"

    def test_eval_condition_no_rules(self):
        with pytest.raises(AppError):
            workflow_engine._eval_condition({"rules": []}, {})

    def test_eval_condition_bad_expression_skipped(self):
        node = {"rules": [{"when": "risk_score <<< 85", "goto": "x"},
                          {"when": "default", "goto": "y"}]}
        with pytest.raises(AppError):
            workflow_engine._eval_condition(node, {"risk_score": 60})

    def test_eval_context_camel_and_snake(self):
        inst = helpers.make_instance.__self__ if False else None  # placeholder
        from app.models.workflow import WorkflowInstance

        inst = WorkflowInstance(context_snapshot={"score": 90, "amount": 1000, "highRisk": 2,
                                                  "riskTotal": 5, "contract_type": "purchase"})
        ctx = workflow_engine._eval_context(inst)
        assert ctx["risk_score"] == 90
        assert ctx["high_risk"] == 2
        assert ctx["risk_level"] == "high"

        inst2 = WorkflowInstance(context_snapshot={"risk_score": 90, "high_risk": 0})
        ctx2 = workflow_engine._eval_context(inst2)
        assert ctx2["risk_level"] == "none"
        assert ctx2["amount"] == 0

    def test_eval_context_empty(self):
        from app.models.workflow import WorkflowInstance

        ctx = workflow_engine._eval_context(WorkflowInstance(context_snapshot=None))
        assert ctx["score"] == 0 and ctx["risk_level"] == "none"

    def test_trace_condition(self, wf_env, db):
        inst = helpers.make_instance(db, wf_env["definition"].id, wf_env["contract"].id)
        node = {"id": "c1", "name": "条件判断", "rules": [{"when": "risk_score < 85", "goto": "n1"}]}
        nodes = {"c1": node, "n1": {"id": "n1", "name": "部门经理审批"}}
        workflow_engine._trace_condition(db, inst, node, "n1", nodes)
        db.commit()
        records = [r for r in inst.records if r.node_id == "c1"]
        assert records and "风险" not in records[0].comment
        assert "规则命中" in records[0].comment

    def test_trace_condition_default_desc(self, wf_env, db):
        inst = helpers.make_instance(db, wf_env["definition"].id, wf_env["contract"].id)
        node = {"id": "c1", "name": "条件判断", "rules": [{"when": "default", "goto": "n1"}]}
        workflow_engine._trace_condition(db, inst, node, "n1", {"n1": {"name": "审批"}})
        db.commit()
        records = [r for r in inst.records if r.node_id == "c1"]
        assert "default" in records[0].comment


class TestAdvanceAndFinish:
    def test_advance_to_approval_node(self, wf_env, db):
        inst = helpers.make_instance(db, wf_env["definition"].id, wf_env["contract"].id)
        db.commit()
        workflow_engine._advance_from(db, inst, wf_env["definition"], "start")
        db.commit()
        db.expire_all()
        assert inst.current_node_id == "n1"
        assert inst.current_node_name == "部门经理审批"
        assert inst.status == "running"

    def test_advance_through_cc_auto_pass(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id)
        graph = helpers.approval_graph(
            nodes=[
                {"id": "cc1", "type": "cc", "name": "抄送领导", "assignees": ["role:boss"]},
                {"id": "n1", "type": "approval", "name": "部门经理审批", "assignees": ["role:dept_manager"]},
            ],
            edges=[{"from": "start", "to": "cc1"}, {"from": "cc1", "to": "n1"},
                   {"from": "n1", "to": "end"}],
        )
        definition = helpers.make_definition(db, graph=graph)
        inst = helpers.make_instance(db, definition.id, contract.id)
        db.commit()
        workflow_engine._advance_from(db, inst, definition, "start")
        db.commit()
        db.expire_all()
        assert inst.current_node_id == "n1"
        cc_records = [r for r in inst.records if r.node_id == "cc1"]
        assert cc_records and "已抄送" in cc_records[0].comment

    def test_advance_condition_branch(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id)
        graph = helpers.approval_graph(
            nodes=[
                {"id": "c1", "type": "condition", "name": "风险分流", "rules": [
                    {"when": "risk_score < 85 or amount >= 1000000", "goto": "n1"},
                    {"when": "default", "goto": "n2"},
                ]},
                {"id": "n1", "type": "approval", "name": "普通审批", "assignees": ["role:dept_manager"]},
                {"id": "n2", "type": "approval", "name": "加签审批", "assignees": ["role:dept_manager"]},
            ],
            edges=[{"from": "start", "to": "c1"}, {"from": "c1", "to": "n1"},
                   {"from": "n1", "to": "n2"}, {"from": "n2", "to": "end"}],
        )
        definition = helpers.make_definition(db, graph=graph)
        # A chosen approval node must be entered.
        low = helpers.make_instance(db, definition.id, contract.id,
                                   context_snapshot={"score": 60, "amount": 2000000})
        db.commit()
        workflow_engine._advance_from(db, low, definition, "start")
        db.commit()
        db.expire_all()
        assert low.current_node_id == "n1"
        assert any(r.node_id == "c1" and "规则命中" in r.comment for r in low.records)

        # The default branch also enters its chosen approval node.
        high = helpers.make_instance(db, definition.id, contract.id,
                                     context_snapshot={"score": 95, "amount": 100})
        db.commit()
        workflow_engine._advance_from(db, high, definition, "start")
        db.commit()
        db.expire_all()
        assert high.current_node_id == "n2"
        assert high.status == "running"

    def test_advance_missing_edge_fails_closed(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id)
        definition = helpers.make_definition(db, graph=helpers.approval_graph(nodes=[], edges=[]))
        inst = helpers.make_instance(db, definition.id, contract.id)
        db.commit()
        with pytest.raises(AppError):
            workflow_engine._advance_from(db, inst, definition, "start")
        assert inst.status == "running"
        assert contract.status != "approved"

    def test_advance_cycle_fails_closed(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id)
        definition = helpers.make_definition(db, graph={"nodes": [
            {"id": "loop", "type": "condition", "rules": [{"when": "default", "goto": "loop"}]}],
            "edges": [{"from": "start", "to": "loop"}]})
        inst = helpers.make_instance(db, definition.id, contract.id)
        db.commit()
        with pytest.raises(AppError):
            workflow_engine._advance_from(db, inst, definition, "start")
        assert inst.status == "running"

    def test_finish_rejected(self, wf_env, db):
        inst = helpers.make_instance(db, wf_env["definition"].id, wf_env["contract"].id)
        db.commit()
        workflow_engine._finish(inst, "rejected", "已否决", db)
        db.commit()
        db.expire_all()
        assert inst.current_node_name == "已否决"
        assert wf_env["contract"].status == "rejected"


class TestSignProgress:
    def test_or_mode_records_stable_user_id(self, wf_env, db):
        inst = helpers.make_instance(db, wf_env["definition"].id, wf_env["contract"].id,
                                     current_node_id="n1")
        node = {"id": "n1", "type": "approval", "signMode": "or", "assignees": ["role:dept_manager"]}
        assert workflow_engine._apply_sign_progress(db, inst, wf_env["definition"], node, _manager_user())
        assert inst.node_state["n1"]["done"] == [2]

    def test_missing_assignments_rejected(self, wf_env, db):
        inst = helpers.make_instance(db, wf_env["definition"].id, wf_env["contract"].id)
        with pytest.raises(AppError):
            workflow_engine._apply_sign_progress(db, inst, wf_env["definition"],
                                                  {"assignees": []}, _manager_user())


class TestStartInstance:
    def test_disabled_definition(self, wf_env, db):
        wf_env["definition"].enabled = False
        db.commit()
        with pytest.raises(AppError) as ei:
            workflow_engine.start_instance(db, wf_env["definition"], wf_env["contract"], 1, "管理员", {})
        assert ei.value.detail["code"] == "WORKFLOW_DEF_DISABLED"

    def test_start_happy_path(self, wf_env, db):
        inst = workflow_engine.start_instance(
            db, wf_env["definition"], wf_env["contract"], 1, "管理员",
            {"score": 90, "highRisk": 0, "riskTotal": 2})
        db.commit()
        db.expire_all()
        assert inst.current_node_id == "n1"
        assert inst.status == "running"
        submit = [r for r in inst.records if r.action == "submit"]
        assert submit and "评分 90" in submit[0].comment

    def test_start_to_end_when_no_approval(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id)
        definition = helpers.make_definition(db, graph=helpers.approval_graph(nodes=[], edges=[{"from": "start", "to": "end"}]))
        inst = workflow_engine.start_instance(db, definition, contract, 1, "管理员", {})
        db.commit()
        db.expire_all()
        assert inst.status == "approved"


class TestCanHandle:
    def test_no_assignees_rejects_all(self):
        assert workflow_engine._can_handle({}, _manager_user()) is False

    def test_role_match(self):
        node = {"assignees": ["role:dept_manager"]}
        assert workflow_engine._can_handle(node, _manager_user()) is True

    def test_user_match(self):
        node = {"assignees": ["user:mgr"]}
        assert workflow_engine._can_handle(node, _manager_user()) is True

    def test_admin_bypass(self, admin_user):
        assert workflow_engine._can_handle({"assignees": ["role:other"]}, admin_user) is True

    def test_no_match(self):
        node = {"assignees": ["role:boss", "user:other"]}
        assert workflow_engine._can_handle(node, _manager_user()) is False


class TestAct:
    def _running_instance(self, wf_env, db, node_id="n1"):
        inst = helpers.make_instance(db, wf_env["definition"].id, wf_env["contract"].id,
                                     current_node_id=node_id)
        helpers.make_approval_record(db, inst.id, node_id="start", action="submit")
        db.commit()
        return inst

    def test_not_running(self, wf_env, db):
        inst = helpers.make_instance(db, wf_env["definition"].id, wf_env["contract"].id,
                                     status="approved")
        db.commit()
        with pytest.raises(AppError) as ei:
            workflow_engine.act(db, inst, action="approve", operator=_manager_user(), comment="")
        assert ei.value.detail["code"] == "WORKFLOW_FINISHED"

    def test_invalid_action(self, wf_env, db):
        inst = self._running_instance(wf_env, db)
        with pytest.raises(AppError) as ei:
            workflow_engine.act(db, inst, action="hack", operator=_manager_user(), comment="")
        assert ei.value.detail["code"] == "WORKFLOW_INVALID_ACTION"

    def test_not_assignee(self, wf_env, db):
        inst = self._running_instance(wf_env, db)
        from app.models.user import Role, User

        stranger = User(id=3, username="stranger", password_hash="x", real_name="陌生人",
                        roles=[Role(id=9, code="staff", name="员工")])
        with pytest.raises(AppError) as ei:
            workflow_engine.act(db, inst, action="approve", operator=stranger, comment="")
        assert ei.value.status_code == 403

    def test_approve_advances_to_end(self, wf_env, db):
        inst = self._running_instance(wf_env, db)
        workflow_engine.act(db, inst, action="approve", operator=_manager_user(), comment="同意")
        db.commit()
        db.expire_all()
        assert inst.status == "approved"
        approve = [r for r in inst.records if r.action == "approve"]
        assert approve and approve[0].operator_name == "经理"

    def test_reject(self, wf_env, db):
        inst = self._running_instance(wf_env, db)
        workflow_engine.act(db, inst, action="reject", operator=_manager_user(), comment="不同意")
        db.commit()
        db.expire_all()
        assert inst.status == "rejected"
        assert inst.current_node_name == "已否决"

    def test_return_to_previous_node(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id)
        graph = helpers.approval_graph(
            nodes=[{"id": "n1", "type": "approval", "name": "部门经理审批", "assignees": ["role:dept_manager"]},
                   {"id": "n2", "type": "approval", "name": "法务审批", "assignees": ["role:dept_manager"]}],
            edges=[{"from": "start", "to": "n1"}, {"from": "n1", "to": "n2"},
                   {"from": "n2", "to": "end"}],
        )
        definition = helpers.make_definition(db, graph=graph)
        inst = helpers.make_instance(db, definition.id, contract.id, current_node_id="n2")
        helpers.make_approval_record(db, inst.id, node_id="start", action="submit")
        helpers.make_approval_record(db, inst.id, node_id="n1", action="approve", operator_name="经理")
        db.commit()
        workflow_engine.act(db, inst, action="return", operator=_manager_user(), comment="退回补充")
        db.commit()
        db.expire_all()
        assert inst.current_node_id == "n1"

    def test_return_without_history_fails_closed(self, wf_env, db):
        # Correct the wrong expectation: with no history to fall back to, it must error and stop; do not hard-code a fallback to n1 (which would bypass the real approval path)
        graph = helpers.approval_graph(
            nodes=[{"id": "n1", "type": "approval", "name": "部门经理审批", "assignees": ["role:dept_manager"]},
                   {"id": "n2", "type": "approval", "name": "法务审批", "assignees": ["role:dept_manager"]}],
            edges=[{"from": "start", "to": "n1"}, {"from": "n1", "to": "n2"},
                   {"from": "n2", "to": "end"}],
        )
        definition = helpers.make_definition(db, graph=graph)
        inst = helpers.make_instance(db, definition.id, wf_env["contract"].id, current_node_id="n2")
        db.commit()
        with pytest.raises(AppError) as error:
            workflow_engine.act(db, inst, action="return", operator=_manager_user(), comment="退回")
        assert error.value.status_code == 400
        db.commit()
        db.expire_all()
        assert inst.current_node_id == "n2"
        assert inst.status == "running"

    @pytest.mark.parametrize("action", ["transfer", "countersign"])
    def test_unsupported_delegation_rejected(self, wf_env, db, action):
        inst = self._running_instance(wf_env, db)
        with pytest.raises(AppError):
            workflow_engine.act(db, inst, action=action, operator=_manager_user(), comment="")
        db.expire_all()
        assert not any(r.action == action for r in inst.records)
        assert inst.current_node_id == "n1"

    def test_and_mode_partial_stays(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id)
        graph = helpers.approval_graph(
            nodes=[{"id": "n1", "type": "approval", "name": "部门经理审批", "signMode": "and",
                    "assignees": ["role:dept_manager", "role:b"]}],
        )
        definition = helpers.make_definition(db, graph=graph)
        inst = helpers.make_instance(db, definition.id, contract.id, current_node_id="n1")
        db.commit()
        workflow_engine.act(db, inst, action="approve", operator=_manager_user(), comment="1")
        db.commit()
        db.expire_all()
        assert inst.status == "running"  # 未签完
        assert inst.node_state["n1"]["done"] == [2]


class TestWithdrawUrge:
    def test_withdraw_not_running(self, wf_env, db):
        inst = helpers.make_instance(db, wf_env["definition"].id, wf_env["contract"].id,
                                     status="approved")
        db.commit()
        with pytest.raises(AppError) as ei:
            workflow_engine.withdraw(db, inst, "原因")
        assert ei.value.detail["code"] == "WORKFLOW_FINISHED_WITHDRAW"

    def test_withdraw_happy(self, wf_env, db):
        inst = helpers.make_instance(db, wf_env["definition"].id, wf_env["contract"].id)
        db.commit()
        workflow_engine.withdraw(db, inst, "计划变更")
        db.commit()
        db.expire_all()
        assert inst.status == "withdrawn"
        assert inst.finished_at is not None
        assert wf_env["contract"].status == "review_passed"
        assert any(r.action == "withdraw" for r in inst.records)

    def test_urge_not_running(self, wf_env, db):
        inst = helpers.make_instance(db, wf_env["definition"].id, wf_env["contract"].id,
                                     status="approved")
        db.commit()
        with pytest.raises(AppError) as ei:
            workflow_engine.urge(db, inst, "张三")
        assert ei.value.detail["code"] == "WORKFLOW_FINISHED_URGE"

    def test_urge_happy(self, wf_env, db):
        inst = helpers.make_instance(db, wf_env["definition"].id, wf_env["contract"].id)
        db.commit()
        workflow_engine.urge(db, inst, "张三", "zhangsan")
        db.commit()
        db.expire_all()
        assert any(r.action == "urge" for r in inst.records)
        from app.models.knowledge import Notification

        notifications = db.query(Notification).filter(Notification.type == "approval_todo").all()
        assert notifications and "催办" in notifications[0].title


class TestScanTimeout:
    def test_no_timeout_config(self, wf_env, db):
        helpers.make_instance(db, wf_env["definition"].id, wf_env["contract"].id)
        db.commit()
        assert workflow_engine.scan_timeout(db) == 0

    def test_timeout_triggers_notification(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id)
        graph = helpers.approval_graph(
            nodes=[{"id": "n1", "type": "approval", "name": "部门经理审批", "timeoutHours": 1, "assignees": ["role:dept_manager"]}],
        )
        definition = helpers.make_definition(db, graph=graph)
        helpers.make_instance(db, definition.id, contract.id, current_node_id="n1",
                             started_at=datetime.now() - timedelta(hours=5))
        db.commit()
        assert workflow_engine.scan_timeout(db) == 1
        from app.models.knowledge import Notification

        db.expire_all()
        notifications = db.query(Notification).filter(Notification.type == "approval_timeout").all()
        assert notifications and "超时" in notifications[0].title

    def test_timeout_uses_last_record_anchor(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id)
        graph = helpers.approval_graph(
            nodes=[{"id": "n1", "type": "approval", "name": "部门经理审批", "timeout_hours": 1, "assignees": ["role:dept_manager"]}],
        )
        definition = helpers.make_definition(db, graph=graph)
        inst = helpers.make_instance(db, definition.id, contract.id, current_node_id="n1",
                                     started_at=datetime.now() - timedelta(hours=5))
        helpers.make_approval_record(db, inst.id, node_id="n1", action="approve",
                                     created_at=datetime.now() - timedelta(minutes=10))
        db.commit()
        assert workflow_engine.scan_timeout(db) == 0  # 最近记录在时限内

    def test_missing_definition_skipped(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id)
        helpers.make_instance(db, 99999, contract.id, current_node_id="n1")
        db.commit()
        assert workflow_engine.scan_timeout(db) == 0


class TestPickDefinition:
    def test_exact_type_match(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id, contract_type="purchase")
        helpers.make_definition(db, name="采购流", contract_types=["purchase"])
        helpers.make_definition(db, name="通用流", contract_types=None)
        db.commit()
        assert workflow_engine.pick_definition_for_contract(db, contract).name == "采购流"

    def test_all_type_fallback(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id, contract_type="labor")
        helpers.make_definition(db, name="通用流", contract_types=["purchase", "sales", "labor",
                                                                   "lease", "nda", "other"])
        db.commit()
        assert workflow_engine.pick_definition_for_contract(db, contract).name == "通用流"

    def test_empty_contract_types_fallback(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id, contract_type="labor")
        helpers.make_definition(db, name="空类型流", contract_types=[])
        db.commit()
        assert workflow_engine.pick_definition_for_contract(db, contract).name == "空类型流"

    def test_fallback_to_any(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id, contract_type="labor")
        helpers.make_definition(db, name="其它流", contract_types=["purchase"])
        db.commit()
        assert workflow_engine.pick_definition_for_contract(db, contract).name == "其它流"

    def test_no_definitions(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id)
        db.commit()
        assert workflow_engine.pick_definition_for_contract(db, contract) is None


class TestBuilders:
    def test_build_definition_out(self, wf_env):
        out = workflow_engine.build_definition_out(wf_env["definition"])
        assert out["name"] == "标准合同审批流"
        assert out["contractTypes"] == ["purchase"]
        assert out["nodes"] and out["edges"]
        assert out["enabled"] is True
        assert out["updatedAt"] == wf_env["definition"].updated_at.strftime("%Y-%m-%dT%H:%M:%S")

    def test_build_instance_out(self, wf_env, db):
        inst = helpers.make_instance(db, wf_env["definition"].id, wf_env["contract"].id,
                                     context_snapshot={"score": 90})
        helpers.make_approval_record(db, inst.id, node_id="start", action="submit")
        db.commit()
        out = workflow_engine.build_instance_out(inst, wf_env["contract"])
        assert out["contractTitle"] == wf_env["contract"].title
        assert out["contextSnapshot"]["score"] == 90
        assert len(out["records"]) == 1
        assert out["startedAt"] == inst.started_at.strftime("%Y-%m-%dT%H:%M:%S")

    def test_build_instance_out_no_contract(self, wf_env, db):
        inst = helpers.make_instance(db, wf_env["definition"].id, wf_env["contract"].id)
        db.commit()
        out = workflow_engine.build_instance_out(inst, None)
        assert out["contractTitle"] == ""
        assert out["finishedAt"] is None

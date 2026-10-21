"""Authorization regressions: real JWT + real endpoints + isolated database.

The tests intentionally do not override get_current_user or require_perm.
"""
import pytest
from fastapi.testclient import TestClient

from app.core import security
from app.db.session import get_db
from app.main import app
from app.models.knowledge import Notification
from tests import helpers

API = "/api/v1"


@pytest.fixture
def secured(db, session_factory, monkeypatch):
    monkeypatch.setattr("app.services.contract_service.submit_parse_task", lambda *_: None)
    monkeypatch.setattr("app.api.v1.reviews.submit_review_task", lambda *_: None)
    permissions = [helpers.make_permission(db, code=code) for code in (
        "contract:upload", "contract:download", "contract:delete", "review:rerun", "review:resolve", "review:export")]
    role = helpers.make_role(db, code="scoped", data_scope="self", permissions=permissions)
    viewer = helpers.make_user(db, username="viewer", dept_name="采购部", roles=[role])
    peer = helpers.make_user(db, username="peer", dept_name="采购部")
    outsider = helpers.make_user(db, username="outsider", dept_name="销售部")
    own = helpers.make_contract(db, owner_id=viewer.id, title="own")
    same = helpers.make_contract(db, owner_id=peer.id, title="same")
    other = helpers.make_contract(db, owner_id=outsider.id, title="other", status="approved")
    version = helpers.make_version(db, other.id, parse_status="parsed")
    clause = helpers.make_clause(db, version.id, other.id, content="private contract text")
    task = helpers.make_review_task(db, other.id, version_id=version.id, status="completed")
    helpers.make_report(db, task.id, other.id)
    finding = helpers.make_finding(db, task.id, clause_id=clause.id, suggested_text="replacement")
    prompt = helpers.make_prompt(db)
    model = helpers.make_model_version(db)
    template = helpers.make_template(db)
    law = helpers.make_law(db)
    notification = helpers.make_notification(db, user_id=outsider.id)
    db.commit()

    def override_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app, headers={"Authorization": "Bearer " + security.create_access_token(viewer.id, viewer.username)})
    yield dict(client=client, viewer=viewer, peer=peer, outsider=outsider, own=own, same=same,
               other=other, version=version, clause=clause, task=task, finding=finding,
               prompt=prompt, model=model, template=template, law=law, role=role, notification=notification)
    client.close()
    app.dependency_overrides.clear()


def test_missing_token_denied(secured):
    assert secured["client"].get(f"{API}/contracts", headers={"Authorization": ""}).status_code == 401


@pytest.mark.parametrize("scope,expected", [("self", {"own"}), ("dept", {"own", "same"}),
                                            ("all", {"own", "same", "other"}), ("invalid", {"own"})])
def test_list_enforces_scope(secured, db, scope, expected):
    secured["role"].data_scope = scope
    db.commit()
    response = secured["client"].get(f"{API}/contracts")
    assert response.status_code == 200
    assert {item["title"] for item in response.json()} == expected


@pytest.mark.parametrize("suffix", ["", "/versions", "/download"])
def test_other_contract_denied(secured, suffix):
    response = secured["client"].get(f"{API}/contracts/{secured['other'].id}{suffix}")
    assert response.status_code == 403


def test_other_version_clauses_denied(secured):
    client = secured["client"]
    assert client.get(f"{API}/contracts/versions/{secured['version'].id}/clauses").status_code == 403
    assert client.get(f"{API}/contracts/{secured['other'].id}/versions/{secured['version'].id}/clauses").status_code == 403


@pytest.mark.parametrize("suffix", ["", "/progress", "/report", "/export"])
def test_other_review_denied(secured, suffix):
    assert secured["client"].get(f"{API}/review-tasks/{secured['task'].id}{suffix}").status_code == 403


def test_review_and_finding_lists_filtered(secured):
    for path in ("review-tasks", "findings"):
        response = secured["client"].get(f"{API}/{path}")
        assert response.status_code == 200
        assert response.json() == []


def test_other_finding_cannot_be_mutated(secured, db):
    response = secured["client"].put(f"{API}/findings/{secured['finding'].id}/status", json={"status": "accepted"})
    assert response.status_code == 403
    db.expire_all()
    assert db.get(type(secured["clause"]), secured["clause"].id).content == "private contract text"


def test_other_contract_cannot_be_archived(secured, db):
    response = secured["client"].post(f"{API}/contracts/{secured['other'].id}/archive")
    assert response.status_code == 403
    db.expire_all()
    assert db.get(type(secured["other"]), secured["other"].id).status == "approved"


@pytest.mark.parametrize("method,path,payload", [
    ("get", "/users", None), ("get", "/roles", None), ("get", "/audit-logs", None),
    ("get", "/prompts", None), ("get", "/model-versions", None),
    ("put", "/prompts/{prompt}/content", {"content": "tampered"}),
    ("post", "/prompts/{prompt}/activate", {}), ("post", "/model-versions/{model}/default", {}),
    ("post", "/laws", {"title": "x", "content": "tampered"}),
    ("post", "/laws/{law}/expire", {}),
    ("post", "/templates", {"name": "x", "contractType": "purchase", "content": "tampered"}),
    ("delete", "/templates/{template}", None),
])
def test_unprivileged_management_denied(secured, method, path, payload):
    path = path.format(**{name: secured[name].id for name in ("prompt", "model", "law", "template")})
    kwargs = {"json": payload} if payload is not None else {}
    response = getattr(secured["client"], method)(API + path, **kwargs)
    assert response.status_code == 403, (path, response.text)


def test_foreign_notification_cannot_be_marked_read(secured, db):
    response = secured["client"].post(f"{API}/notifications/{secured['notification'].id}/read")
    assert response.status_code == 403
    db.expire_all()
    assert db.get(Notification, secured["notification"].id).read is False


def test_upload_dedupe_does_not_return_foreign_contract(secured, db, monkeypatch):
    from app.services import contract_service
    from app.utils.files import sha256_bytes

    secured["other"].file_sha256 = sha256_bytes(b"synthetic file")
    db.commit()
    monkeypatch.setattr(contract_service, "submit_parse_task", lambda *_: None)
    created = contract_service.create_contract(db, owner=secured["viewer"], file_name="test.pdf", file_bytes=b"synthetic file",
                                              title="new", contract_type="purchase", counterparty_name="", amount=1)
    assert created.owner_id == secured["viewer"].id
    assert created.id != secured["other"].id


def test_foreign_version_cannot_be_uploaded(secured):
    response = secured["client"].post(f"{API}/contracts/{secured['other'].id}/versions",
                                     files={"file": ("new.pdf", b"synthetic", "application/pdf")})
    assert response.status_code == 403


def test_own_contract_access_survives(secured):
    response = secured["client"].get(f"{API}/contracts/{secured['own'].id}")
    assert response.status_code == 200, response.text


def test_authorized_prompt_editor_can_publish(secured, db):
    permission = helpers.make_permission(db, code="system:prompt")
    secured["role"].permissions.append(permission)
    db.commit()
    response = secured["client"].put(f"{API}/prompts/{secured['prompt'].id}/content", json={"content": "authorized"})
    assert response.status_code == 200
    db.expire_all()
    assert db.get(type(secured["prompt"]), secured["prompt"].id).content == "authorized"

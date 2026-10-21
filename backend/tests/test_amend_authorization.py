"""Audit regression: adopting a finding suggestion is contract **write** capability.

Adopting a suggestion creates a new version and materializes an amended DOCX -- equivalent to
contract:upload -- so review:resolve alone must not rewrite the contract body, and an amendment must
never resurrect a terminal (archived) contract or silently pull a contract out of a running approval.
"""
from __future__ import annotations

import pytest

from app.core.exceptions import AppError
from app.models.contract import ContractClause
from app.models.review import ReviewReport, ReviewTask, RiskFinding
from app.services import contract_service
from tests import helpers

API = "/api/v1"
ORIGINAL = "第一条 付款：甲方支付部分价款。"
SUGGESTED = "第一条 付款：甲方支付全部价款。"


@pytest.fixture(autouse=True)
def _no_side_effects(monkeypatch):
    monkeypatch.setattr("app.services.contract_service.index_clauses_to_es", lambda *a, **k: None)
    monkeypatch.setattr("app.services.contract_service.submit_parse_task", lambda *a, **k: None)


@pytest.fixture()
def env(db):
    """A legal reviewer owning a review_passed contract: review:resolve but NOT contract:upload."""
    resolve = helpers.make_permission(db, code="review:resolve")
    role = helpers.make_role(db, code="legal_reviewer", data_scope="self", permissions=[resolve])
    reviewer = helpers.make_user(db, username="zhangmy", roles=[role])
    contract = helpers.make_contract(db, owner_id=reviewer.id, status="review_passed", current_version=1)
    version = helpers.make_version(db, contract.id, version_no=1, parse_status="parsed")
    clause = helpers.make_clause(db, version.id, contract.id, clause_no="第一条", content=ORIGINAL)
    task = helpers.make_review_task(db, contract.id, version_id=version.id, status="completed")
    report = helpers.make_report(db, task.id, contract.id, score=90)
    finding = helpers.make_finding(db, task.id, clause_id=clause.id, clause_no="第一条", suggested_text=SUGGESTED)
    db.commit()
    return {"user": reviewer, "role": role, "contract": contract, "version": version,
            "clause": clause, "task": task, "report": report, "finding": finding}


def _as(client, env):
    client.user_state["user_id"] = env["user"].id
    return client


def _accept(client, finding_id):
    return client.put(f"{API}/findings/{finding_id}/status", json={"status": "accepted"})


def _clause_text(db, version_id):
    return db.query(ContractClause).filter_by(version_id=version_id, clause_no="第一条").one().content


class TestAuthorization:
    def test_resolve_only_cannot_amend_contract(self, client, env, db):
        resp = _accept(_as(client, env), env["finding"].id)
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"]["code"] == "PERM_DENIED"
        db.expire_all()
        assert _clause_text(db, env["version"].id) == ORIGINAL
        assert db.get(type(env["contract"]), env["contract"].id).current_version == 1
        assert db.get(RiskFinding, env["finding"].id).status == "open"
        assert db.query(ContractClause).filter_by(version_id=env["version"].id).count() == 1

    def test_upload_permission_allows_amendment(self, client, env, db):
        env["role"].permissions.append(helpers.make_permission(db, code="contract:upload"))
        db.commit()
        resp = _accept(_as(client, env), env["finding"].id)
        assert resp.status_code == 200, resp.text
        assert resp.json()["applied"] is True
        db.expire_all()
        contract = db.get(type(env["contract"]), env["contract"].id)
        assert contract.current_version == 2
        new_version = db.query(type(env["version"])).filter_by(contract_id=contract.id, version_no=2).one()
        assert _clause_text(db, new_version.id) == SUGGESTED
        assert _clause_text(db, env["version"].id) == ORIGINAL  # old version stays immutable
        assert contract.status == "parsed"  # amendment invalidates the previous review conclusion
        assert db.get(RiskFinding, env["finding"].id).status == "fixed"

    def test_admin_may_amend_without_explicit_upload_grant(self, client, env, db):
        """The default client fixture is admin: require_perm/ensure_perm both treat admin as all-power."""
        resp = _accept(client, env["finding"].id)
        assert resp.status_code == 200, resp.text
        db.expire_all()
        assert db.get(type(env["contract"]), env["contract"].id).current_version == 2

    def test_accept_without_suggested_text_needs_no_upload_permission(self, client, env, db):
        env["finding"].suggested_text = None
        db.commit()
        resp = _accept(_as(client, env), env["finding"].id)
        assert resp.status_code == 200, resp.text
        assert resp.json()["applied"] is False
        db.expire_all()
        assert db.get(type(env["contract"]), env["contract"].id).current_version == 1

    def test_reject_and_open_are_unaffected(self, client, env, db):
        user_client = _as(client, env)
        finding_id = env["finding"].id
        assert user_client.put(f"{API}/findings/{finding_id}/status",
                               json={"status": "rejected"}).status_code == 200
        assert user_client.put(f"{API}/findings/{finding_id}/status",
                               json={"status": "open"}).status_code == 200
        db.expire_all()
        assert db.get(type(env["contract"]), env["contract"].id).current_version == 1


class TestStatusGuards:
    def test_archived_contract_is_terminal(self, env, db):
        env["contract"].status = "archived"
        db.commit()
        with pytest.raises(AppError) as exc:
            contract_service.amend_clause(db, env["clause"], SUGGESTED)
        assert exc.value.detail["code"] == "CONTRACT_ARCHIVED_NO_AMEND"
        assert exc.value.status_code == 400
        db.expire_all()
        assert db.get(type(env["contract"]), env["contract"].id).current_version == 1
        assert db.get(type(env["contract"]), env["contract"].id).status == "archived"

    def test_in_approval_must_be_withdrawn_first(self, env, db):
        env["contract"].status = "in_approval"
        db.commit()
        with pytest.raises(AppError) as exc:
            contract_service.amend_clause(db, env["clause"], SUGGESTED)
        assert exc.value.detail["code"] == "CONTRACT_IN_APPROVAL_NO_AMEND"
        db.expire_all()
        assert db.get(type(env["contract"]), env["contract"].id).current_version == 1

    def test_guard_is_hit_through_the_api_too(self, client, env, db):
        env["contract"].status = "archived"
        db.commit()
        resp = _accept(client, env["finding"].id)
        assert resp.status_code == 400, resp.text
        assert resp.json()["detail"]["code"] == "CONTRACT_ARCHIVED_NO_AMEND"
        db.expire_all()
        assert db.get(type(env["contract"]), env["contract"].id).current_version == 1

    def test_amendment_still_invalidates_prior_report(self, client, env, db):
        """Happy path preserved: old reports lose approval eligibility after content change."""
        resp = _accept(client, env["finding"].id)
        assert resp.status_code == 200, resp.text
        db.expire_all()
        assert db.get(ReviewReport, env["report"].id).report_json["summary"]["needsReReview"] is True
        assert db.get(ReviewTask, env["task"].id).status == "completed"
"""Batch 3 regression: report-bound version + content hash, independent approval-eligibility (audit counterexamples must all be handled correctly).

Acceptance: after amendment, uploading a new version, or partial-review failure, old reports must no longer authorize approval;
old tasks must not overwrite the new-version status; historical reports are flagged for re-review.
"""
from __future__ import annotations

import pytest

from app.ai import llm_client
from app.db.security_upgrade import migrate_legacy_reports
from app.models.contract import Contract, ContractClause, ContractVersion
from app.models.review import ReviewReport, ReviewTask
from app.services import approval_gate, contract_service, review_service
from tests import helpers

API = "/api/v1"


def _graph_out(**stat_overrides):
    stats = {"high": 0, "medium": 0, "low": 0, "ai_high": 0, "ai_medium": 0, "ai_low": 0,
             "score": 95, "failed_clauses": 0}
    stats.update(stat_overrides)
    return {"findings": [], "stats": stats, "opinion": "建议签署。", "tokens": 10}


def _patch_graph(monkeypatch, out=None, exc=None):
    def fake_graph(db, **kw):
        if exc:
            raise exc
        return out or _graph_out()

    monkeypatch.setattr("app.agents.review_graph.run_review_graph", fake_graph)
    monkeypatch.setattr(llm_client, "ensure_llm_configured", lambda: None)
    monkeypatch.setattr(llm_client, "current_model", lambda: "deepseek-chat")
    monkeypatch.setattr("app.ai.rag.index_report_summary", lambda *a, **k: "doc_1")


@pytest.fixture(autouse=True)
def _no_dispatch(monkeypatch):
    monkeypatch.setattr("app.services.contract_service.submit_parse_task", lambda *a, **k: None)


@pytest.fixture()
def env(db):
    user = helpers.make_user(db)
    contract = helpers.make_contract(db, owner_id=user.id, status="review_passed", current_version=1)
    version = helpers.make_version(db, contract.id, version_no=1, parse_status="parsed")
    helpers.make_clause(db, version.id, contract.id, clause_no="第一条", content="付款条款。")
    helpers.make_clause(db, version.id, contract.id, clause_no="第二条", content="争议条款：提交仲裁。")
    task = helpers.make_review_task(db, contract.id, version_id=version.id, status="completed")
    helpers.make_definition(db, graph=helpers.approval_graph())
    db.commit()
    return {"user": user, "contract": contract, "version": version, "task": task}


# ===================== Independent approval-eligibility =====================
class TestApprovalEligibility:
    def test_valid_full_report_is_eligible(self, client, env, db):
        helpers.make_report(db, env["task"].id, env["contract"].id, score=90)
        db.commit()
        resp = client.post(f"{API}/workflow/instances", json={"contractId": env["contract"].id})
        assert resp.status_code == 200

    def test_incomplete_report_cannot_authorize_approval(self, client, env, db):
        """Audit counterexample: a report with failedClauses=1, score 100, no high risk must not pass approval."""
        helpers.make_report(db, env["task"].id, env["contract"].id, score=100,
                            report_json={"summary": {"failedClauses": 1}})
        db.commit()
        resp = client.post(f"{API}/workflow/instances", json={"contractId": env["contract"].id})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "WORKFLOW_REPORT_INCOMPLETE"

    def test_partial_report_cannot_authorize_approval(self, client, env, db):
        """A single-clause / incremental review report cannot serve as the approval basis for the whole contract."""
        env["task"].task_type = "clause"
        env["task"].clause_no = "第一条"
        db.commit()
        helpers.make_report(db, env["task"].id, env["contract"].id, score=100)
        db.commit()
        resp = client.post(f"{API}/workflow/instances", json={"contractId": env["contract"].id})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "WORKFLOW_NO_REVIEW_REPORT"

    def test_old_version_report_cannot_authorize_approval(self, client, env, db):
        helpers.make_report(db, env["task"].id, env["contract"].id, score=100)
        contract_service.upload_new_version(db, env["contract"], "v2.docx", b"PK\x03\x04fake")
        db.commit()
        # even if the status is force-reset to review_passed (simulating inconsistency), the old report cannot authorize approval
        contract = db.get(Contract, env["contract"].id)
        contract.status = "review_passed"
        db.commit()
        resp = client.post(f"{API}/workflow/instances", json={"contractId": env["contract"].id})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] in ("WORKFLOW_NO_REVIEW_REPORT", "WORKFLOW_REPORT_STALE")
        report = db.query(ReviewReport).one()
        assert report.report_json["summary"]["needsReReview"] is True

    def test_content_change_after_review_invalidates_report(self, client, env, db):
        helpers.make_report(db, env["task"].id, env["contract"].id, score=100)
        # simulate a historical in-place rewrite: the current version's clause content no longer matches the report hash
        clause = db.query(ContractClause).filter_by(version_id=env["version"].id).first()
        clause.content = "被改写的内容。"
        db.commit()
        resp = client.post(f"{API}/workflow/instances", json={"contractId": env["contract"].id})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "WORKFLOW_REPORT_STALE"

    def test_legacy_unbound_report_needs_re_review(self, client, env, db):
        report = helpers.make_report(db, env["task"].id, env["contract"].id, score=100, bind=False)
        db.commit()
        resp = client.post(f"{API}/workflow/instances", json={"contractId": env["contract"].id})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "WORKFLOW_REPORT_STALE"
        # migration rule: historical reports are marked "needs re-review"
        migrate_legacy_reports(db)
        db.expire_all()
        assert report.report_json["summary"]["needsReReview"] is True

    def test_threshold_failures_rejected(self, client, env, db):
        helpers.make_report(db, env["task"].id, env["contract"].id, score=84)
        db.commit()
        resp = client.post(f"{API}/workflow/instances", json={"contractId": env["contract"].id})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "WORKFLOW_THRESHOLD_NOT_MET"
        db.query(ReviewReport).delete()
        db.commit()
        helpers.make_report(db, env["task"].id, env["contract"].id, score=100, high_count=1)
        db.commit()
        resp = client.post(f"{API}/workflow/instances", json={"contractId": env["contract"].id})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "WORKFLOW_THRESHOLD_NOT_MET"


# ===================== Amendment version bump + stale-task isolation =====================
class TestAmendmentAndStaleTasks:
    def test_amendment_creates_new_version_and_invalidates_report(self, client, env, db):
        """Audit counterexample: after accepting a suggestion the version must bump; the old report must not keep authorizing approval."""
        helpers.make_report(db, env["task"].id, env["contract"].id, score=100)
        clause = db.query(ContractClause).filter_by(version_id=env["version"].id, clause_no="第一条").one()
        finding = helpers.make_finding(db, env["task"].id, clause_id=clause.id, clause_no="第一条",
                                       suggested_text="修订后的付款条款。")
        db.commit()
        resp = client.put(f"{API}/findings/{finding.id}/status", json={"status": "accepted"})
        assert resp.status_code == 200
        db.expire_all()
        contract = db.get(Contract, env["contract"].id)
        assert contract.current_version == 2
        assert contract.status == "parsed"  # content changed -> revert to re-reviewable
        report = db.query(ReviewReport).one()
        assert report.report_json["summary"]["needsReReview"] is True
        # old report no longer authorizes approval
        verdict = approval_gate.evaluate(db, contract)
        assert not verdict.eligible

    def test_stale_review_task_does_not_overwrite_new_version_status(self, env, db, monkeypatch):
        """Concurrency: uploading a new version races with an old review task finishing; the old task must not overwrite the new-version status."""
        _patch_graph(monkeypatch)
        task = env["task"]
        task.status = "pending"
        db.commit()
        # upload the new version before the task runs (content/version changed)
        contract_service.upload_new_version(db, env["contract"], "v2.docx", b"PK\x03\x04fake")
        db.commit()
        contract = db.get(Contract, env["contract"].id)
        assert contract.status == "parsing"
        # the old task only finishes now
        review_service.run_review(db, task.id)
        db.expire_all()
        contract = db.get(Contract, env["contract"].id)
        # old task result does not overwrite the new-version status (parsing belongs to the new version's flow)
        assert contract.status == "parsing"
        report = db.query(ReviewReport).one()
        assert report.report_json["summary"]["needsReReview"] is True
        assert not approval_gate.evaluate(db, contract).eligible

    def test_partial_review_completion_keeps_overall_status(self, env, db, monkeypatch):
        """Neither partial-review failure nor completion may change the whole contract's approval-eligibility status."""
        _patch_graph(monkeypatch, out=_graph_out(high=1, score=40))
        contract = db.get(Contract, env["contract"].id)
        contract.status = "review_passed"
        partial = helpers.make_review_task(db, contract.id, version_id=env["version"].id,
                                           task_type="clause", clause_no="第一条", status="pending")
        db.commit()
        review_service.run_review(db, partial.id)
        db.expire_all()
        assert db.get(Contract, contract.id).status == "review_passed"  # not overwritten by a local high risk
        report = db.query(ReviewReport).one()
        assert report.report_json["summary"]["taskType"] == "clause"

    def test_upload_new_version_marks_reports(self, env, db):
        helpers.make_report(db, env["task"].id, env["contract"].id, score=100)
        db.commit()
        contract_service.upload_new_version(db, env["contract"], "v2.docx", b"PK\x03\x04fake")
        db.expire_all()
        report = db.query(ReviewReport).one()
        assert report.report_json["summary"]["needsReReview"] is True

    def test_report_binds_version_and_content_hash(self, env, db, monkeypatch):
        _patch_graph(monkeypatch)
        task = helpers.make_review_task(db, env["contract"].id, version_id=env["version"].id, status="pending")
        db.commit()
        review_service.run_review(db, task.id)
        db.expire_all()
        report = db.query(ReviewReport).filter_by(task_id=task.id).one()
        assert report.version_id == env["version"].id
        assert report.content_hash == review_service.version_content_hash(db, env["version"].id)
        assert report.content_hash

"""API-layer unit tests (part 2): AI review / approval workflow / risk-finding summary."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from tests import helpers

API = "/api/v1"


@pytest.fixture()
def review_env(db):
    user = helpers.make_user(db)
    contract = helpers.make_contract(db, owner_id=user.id, status="parsed")
    version = helpers.make_version(db, contract.id, parse_status="parsed")
    clause = helpers.make_clause(db, version.id, contract.id, clause_no="第一条")
    task = helpers.make_review_task(db, contract.id, version_id=version.id, status="pending")
    db.commit()
    return {"user": user, "contract": contract, "version": version, "clause": clause, "task": task}


# ===================== reviews =====================
class TestReviewsApi:
    def test_list_tasks(self, client, review_env, db):
        resp = client.get(f"{API}/review-tasks")
        assert resp.status_code == 200
        assert resp.json()[0]["id"] == review_env["task"].id

    def test_get_task(self, client, review_env):
        resp = client.get(f"{API}/review-tasks/{review_env['task'].id}")
        assert resp.status_code == 200
        assert resp.json()["contractId"] == review_env["contract"].id

    def test_get_task_404(self, client, db):
        assert client.get(f"{API}/review-tasks/99999").status_code == 404

    def test_task_progress(self, client, review_env):
        resp = client.get(f"{API}/review-tasks/{review_env['task'].id}/progress")
        assert resp.json() == {"taskId": review_env["task"].id, "status": "pending",
                               "progress": 0, "errorMsg": None}

    def test_report_none(self, client, review_env):
        resp = client.get(f"{API}/review-tasks/{review_env['task'].id}/report")
        assert resp.status_code == 200
        assert resp.json() is None

    def test_report_with_findings(self, client, review_env, db):
        task, contract = review_env["task"], review_env["contract"]
        report = helpers.make_report(
            db, task.id, contract.id, score=88, high_count=1,
            report_json={"summary": {"high": 2, "medium": 1, "low": 0, "score": 88,
                                     "blockingHigh": 1, "aiHigh": 1, "aiMedium": 1,
                                     "aiLow": 0, "failedClauses": 2}})
        helpers.make_finding(db, task.id, clause_id=review_env["clause"].id)
        db.commit()
        resp = client.get(f"{API}/review-tasks/{task.id}/report")
        body = resp.json()
        assert body["summary"]["high"] == 2  # report_json takes precedence
        assert body["summary"]["blockingHigh"] == 1
        assert body["summary"]["failedClauses"] == 2
        assert body["meta"]["tokensUsed"] == 0
        assert len(body["findings"]) == 1
        assert body["createdAt"] == report.created_at.strftime("%Y-%m-%dT%H:%M:%S")

    def test_report_legacy_summary_fallback(self, client, review_env, db):
        task, contract = review_env["task"], review_env["contract"]
        helpers.make_report(db, task.id, contract.id, score=70, high_count=1, medium_count=2,
                            low_count=3, report_json=None)
        db.commit()
        body = client.get(f"{API}/review-tasks/{task.id}/report").json()
        assert body["summary"]["high"] == 1  # no report_json -> fall back to column values
        assert body["summary"]["medium"] == 2

    def test_start_review(self, client, review_env, db, monkeypatch):
        submitted = []
        monkeypatch.setattr("app.api.v1.reviews.submit_review_task",
                            lambda tid: submitted.append(tid))
        resp = client.post(f"{API}/review-tasks", json={"contractId": review_env["contract"].id,
                                                        "taskType": "full"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "pending"
        assert body["taskType"] == "full"
        assert submitted
        db.expire_all()
        assert review_env["contract"].status == "under_review"

    def test_start_review_contract_missing(self, client, db):
        resp = client.post(f"{API}/review-tasks", json={"contractId": 99999, "taskType": "full"})
        assert resp.status_code == 404

    def test_start_review_not_parsed(self, client, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id, status="parsing")
        helpers.make_version(db, contract.id, parse_status="pending")
        db.commit()
        resp = client.post(f"{API}/review-tasks", json={"contractId": contract.id})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "REVIEW_NOT_PARSED"

    def test_start_review_invalid_type(self, client, review_env):
        resp = client.post(f"{API}/review-tasks",
                           json={"contractId": review_env["contract"].id, "taskType": "bad"})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "REVIEW_INVALID_TYPE"

    def test_start_review_clause_required(self, client, review_env):
        resp = client.post(f"{API}/review-tasks",
                           json={"contractId": review_env["contract"].id, "taskType": "clause"})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "REVIEW_CLAUSE_REQUIRED"

    def test_start_review_diff_defaults_base(self, client, review_env, db, monkeypatch):
        monkeypatch.setattr("app.api.v1.reviews.submit_review_task", lambda tid: None)
        helpers.make_version(db, review_env["contract"].id, version_no=2, parse_status="parsed")
        review_env["contract"].current_version = 2
        db.commit()
        resp = client.post(f"{API}/review-tasks",
                           json={"contractId": review_env["contract"].id, "taskType": "diff"})
        assert resp.status_code == 200
        db.expire_all()
        from app.models.review import ReviewTask

        task = db.query(ReviewTask).order_by(ReviewTask.id.desc()).first()
        assert task.base_version_no == 1  # default to the previous version

    def test_start_review_idempotent_returns_existing(self, client, review_env, db, monkeypatch):
        monkeypatch.setattr("app.api.v1.reviews.submit_review_task", lambda tid: None)
        payload = {"contractId": review_env["contract"].id, "taskType": "full"}
        first = client.post(f"{API}/review-tasks", json=payload)
        second = client.post(f"{API}/review-tasks", json=payload)
        assert first.json()["id"] == second.json()["id"]  # same in-progress key returns existing

    def test_start_review_recovers_zombie(self, client, review_env, db, monkeypatch):
        monkeypatch.setattr("app.api.v1.reviews.submit_review_task", lambda tid: None)
        contract, version = review_env["contract"], review_env["version"]
        stale = helpers.make_review_task(
            db, contract.id, version_id=version.id, status="pending",
            task_key=f"{version.id}:full:-", created_at=datetime.now() - timedelta(minutes=40))
        contract.status = "under_review"
        db.commit()
        resp = client.post(f"{API}/review-tasks",
                           json={"contractId": contract.id, "taskType": "full"})
        assert resp.status_code == 200
        db.expire_all()
        assert db.get(type(stale), stale.id).status == "failed"  # zombie reclaimed
        assert resp.json()["id"] != stale.id  # new task created

    def test_resolve_finding_accepted_with_suggestion(self, client, review_env, db):
        from app.models.contract import Contract, ContractClause, ContractVersion
        from app.utils.clause_split import classify_clause

        task, clause = review_env["task"], review_env["clause"]
        old_content = clause.content
        finding = helpers.make_finding(
            db, task.id, clause_id=clause.id, clause_no="第一条",
            suggested_text="双方应友好协商解决争议。", status="open")
        db.commit()
        resp = client.put(f"{API}/findings/{finding.id}/status", json={"status": "accepted"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["applied"] is True
        assert body["status"] == "fixed"
        db.expire_all()
        # amendment does not rewrite in place: the old-version clause stays unchanged (immutable); the amendment goes to a new version
        loaded = db.get(type(clause), clause.id)
        assert loaded.content == old_content
        contract = db.get(Contract, review_env["contract"].id)
        assert contract.current_version == 2
        new_version = db.query(ContractVersion).filter_by(contract_id=contract.id, version_no=2).one()
        assert new_version.parent_id == loaded.version_id
        amended = (
            db.query(ContractClause)
            .filter(ContractClause.version_id == new_version.id, ContractClause.clause_no == "第一条")
            .one()
        )
        assert amended.content == "双方应友好协商解决争议。"
        assert amended.clause_type == classify_clause(amended.content)
        # char offsets are consistent within the new version
        assert amended.char_start == 0 and amended.char_end == len(amended.content)

    def test_resolve_finding_accepted_keeps_clause_prefix(self, client, review_env, db):
        task, clause = review_env["task"], review_env["clause"]
        clause.content = "第一条 付款：甲方支付价款。"
        finding = helpers.make_finding(db, task.id, clause_id=clause.id, clause_no="第一条",
                                       suggested_text="甲方支付全款。")
        db.commit()
        resp = client.put(f"{API}/findings/{finding.id}/status", json={"status": "accepted"})
        assert resp.json()["applied"] is True
        db.expire_all()
        assert db.get(type(clause), clause.id).content.startswith("第一条 付款：")

    def test_resolve_finding_accepted_without_suggestion(self, client, review_env, db):
        task, clause = review_env["task"], review_env["clause"]
        finding = helpers.make_finding(db, task.id, clause_id=clause.id, suggested_text=None)
        db.commit()
        resp = client.put(f"{API}/findings/{finding.id}/status", json={"status": "accepted"})
        body = resp.json()
        assert body["applied"] is False
        assert body["status"] == "accepted"

    def test_resolve_finding_rejected(self, client, review_env, db):
        finding = helpers.make_finding(db, review_env["task"].id)
        db.commit()
        resp = client.put(f"{API}/findings/{finding.id}/status", json={"status": "rejected"})
        assert resp.json()["status"] == "rejected"
        assert resp.json()["applied"] is False

    def test_resolve_finding_open(self, client, review_env, db):
        finding = helpers.make_finding(db, review_env["task"].id, status="accepted")
        db.commit()
        resp = client.put(f"{API}/findings/{finding.id}/status", json={"status": "open"})
        assert resp.json()["status"] == "open"

    def test_resolve_finding_invalid_status(self, client, review_env, db):
        finding = helpers.make_finding(db, review_env["task"].id)
        db.commit()
        resp = client.put(f"{API}/findings/{finding.id}/status", json={"status": "bad"})
        assert resp.status_code == 400

    def test_resolve_finding_404(self, client, db):
        resp = client.put(f"{API}/findings/99999/status", json={"status": "accepted"})
        assert resp.status_code == 404

    def test_resolve_finding_reindex_failure_tolerated(self, client, review_env, db, monkeypatch):
        task, clause = review_env["task"], review_env["clause"]
        finding = helpers.make_finding(db, task.id, clause_id=clause.id,
                                       suggested_text="修订后的条款内容。")
        db.commit()

        def _boom(db, version):
            raise RuntimeError("es down")

        monkeypatch.setattr("app.services.contract_service.index_clauses_to_es", _boom)
        resp = client.put(f"{API}/findings/{finding.id}/status", json={"status": "accepted"})
        assert resp.json()["applied"] is True  # ES rebuild failure does not block the amendment

    def test_export_audit_trail(self, client, review_env, db):
        resp = client.post(f"{API}/review-tasks/{review_env['task'].id}/export",
                           json={"format": "pdf"})
        assert resp.status_code == 200
        from app.models.knowledge import AuditLog

        db.expire_all()
        log = db.query(AuditLog).filter_by(action="review.export").one()
        assert "PDF" in log.detail["extra"]

    def test_export_audit_trail_404(self, client, db):
        resp = client.post(f"{API}/review-tasks/99999/export", json={"format": "word"})
        assert resp.status_code == 404

    def test_export_report_word(self, client, review_env, db):
        task, contract = review_env["task"], review_env["contract"]
        helpers.make_report(db, task.id, contract.id, overall_opinion="建议签署")
        helpers.make_finding(db, task.id)
        db.commit()
        resp = client.get(f"{API}/review-tasks/{task.id}/export", params={"format": "word"})
        assert resp.status_code == 200
        assert resp.content[:2] == b"PK"
        # Chinese filename percent-encoded per RFC 5987 (HTTP headers only support latin-1)
        from urllib.parse import quote

        assert f"filename*=UTF-8''{quote(f'审查报告_任务{task.id}.docx')}" in resp.headers["content-disposition"]

    def test_export_report_pdf(self, client, review_env, db):
        task, contract = review_env["task"], review_env["contract"]
        helpers.make_report(db, task.id, contract.id, overall_opinion="建议签署")
        db.commit()
        resp = client.get(f"{API}/review-tasks/{task.id}/export", params={"format": "pdf"})
        assert resp.status_code == 200
        assert resp.content[:5] == b"%PDF-"

    def test_export_report_not_generated(self, client, review_env):
        resp = client.get(f"{API}/review-tasks/{review_env['task'].id}/export")
        assert resp.status_code == 404

    def test_findings_summary_endpoint(self, client, review_env, db):
        helpers.make_finding(db, review_env["task"].id, clause_no="第一条")
        db.commit()
        resp = client.get(f"{API}/findings")
        assert resp.status_code == 200
        body = resp.json()
        assert body[0]["clauseNo"] == "第一条"
        assert body[0]["ragHits"] == []

    def test_findings_summary_rag_hits(self, client, review_env, db):
        helpers.make_finding(db, review_env["task"].id, rag_hits=["《民法典》"])
        db.commit()
        assert client.get(f"{API}/findings").json()[0]["ragHits"] == ["《民法典》"]


# ===================== workflows =====================
class TestWorkflowsApi:
    def _passed_env(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id, status="review_passed")
        definition = helpers.make_definition(db, graph=helpers.approval_graph())
        version = helpers.make_version(db, contract.id, parse_status="parsed")
        task = helpers.make_review_task(db, contract.id, version_id=version.id, status="completed")
        report = helpers.make_report(db, task.id, contract.id, score=90, high_count=0)
        db.commit()
        return {"user": user, "contract": contract, "definition": definition, "report": report}

    def test_list_instances(self, client, db):
        env = self._passed_env(db)
        inst = helpers.make_instance(db, env["definition"].id, env["contract"].id)
        db.commit()
        resp = client.get(f"{API}/workflow/instances")
        assert resp.json()[0]["id"] == inst.id

    def test_get_instance(self, client, db):
        env = self._passed_env(db)
        inst = helpers.make_instance(db, env["definition"].id, env["contract"].id)
        db.commit()
        resp = client.get(f"{API}/workflow/instances/{inst.id}")
        assert resp.json()["contractTitle"] == env["contract"].title

    def test_get_instance_404(self, client, db):
        assert client.get(f"{API}/workflow/instances/99999").status_code == 404

    def test_start_approval(self, client, db):
        env = self._passed_env(db)
        resp = client.post(f"{API}/workflow/instances",
                           json={"contractId": env["contract"].id})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "running"
        assert body["currentNodeId"] == "n1"
        db.expire_all()
        assert env["contract"].status == "in_approval"

    def test_start_approval_contract_missing(self, client, db):
        resp = client.post(f"{API}/workflow/instances", json={"contractId": 99999})
        assert resp.status_code == 404

    def test_start_approval_not_ready(self, client, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id, status="parsed")
        db.commit()
        resp = client.post(f"{API}/workflow/instances", json={"contractId": contract.id})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "WORKFLOW_CONTRACT_NOT_READY"

    def test_start_approval_no_report(self, client, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id, status="review_passed")
        db.commit()
        resp = client.post(f"{API}/workflow/instances", json={"contractId": contract.id})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "WORKFLOW_NO_REVIEW_REPORT"

    def test_start_approval_threshold_not_met(self, client, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id, status="review_passed")
        version = helpers.make_version(db, contract.id, parse_status="parsed")
        task = helpers.make_review_task(db, contract.id, version_id=version.id, status="completed")
        helpers.make_report(db, task.id, contract.id, score=60, high_count=0)
        db.commit()
        resp = client.post(f"{API}/workflow/instances", json={"contractId": contract.id})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "WORKFLOW_THRESHOLD_NOT_MET"

    def test_start_approval_high_risk_blocked(self, client, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id, status="review_passed")
        version = helpers.make_version(db, contract.id, parse_status="parsed")
        task = helpers.make_review_task(db, contract.id, version_id=version.id, status="completed")
        helpers.make_report(db, task.id, contract.id, score=95, high_count=2)
        db.commit()
        resp = client.post(f"{API}/workflow/instances", json={"contractId": contract.id})
        assert resp.status_code == 400

    def test_start_approval_no_definition(self, client, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id, status="review_passed")
        version = helpers.make_version(db, contract.id, parse_status="parsed")
        task = helpers.make_review_task(db, contract.id, version_id=version.id, status="completed")
        helpers.make_report(db, task.id, contract.id, score=90, high_count=0)
        db.commit()
        resp = client.post(f"{API}/workflow/instances", json={"contractId": contract.id})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "WORKFLOW_NO_DEFINITION"

    def test_act_approve(self, client, db):
        env = self._passed_env(db)
        inst = helpers.make_instance(db, env["definition"].id, env["contract"].id,
                                     current_node_id="n1")
        db.commit()
        resp = client.post(f"{API}/workflow/instances/{inst.id}/actions",
                           json={"expectedNodeId": "n1", "action": "approve", "comment": "同意"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

    def test_act_reject(self, client, db):
        env = self._passed_env(db)
        inst = helpers.make_instance(db, env["definition"].id, env["contract"].id,
                                     current_node_id="n1")
        db.commit()
        resp = client.post(f"{API}/workflow/instances/{inst.id}/actions",
                           json={"expectedNodeId": "n1", "action": "reject", "comment": "不同意"})
        assert resp.json()["status"] == "rejected"

    def test_act_404(self, client, db):
        resp = client.post(f"{API}/workflow/instances/99999/actions", json={"expectedNodeId": "n1", "action": "approve"})
        assert resp.status_code == 404

    def test_withdraw(self, client, db):
        env = self._passed_env(db)
        inst = helpers.make_instance(db, env["definition"].id, env["contract"].id,
                                     starter_id=1, starter_name="管理员")
        db.commit()
        resp = client.post(f"{API}/workflow/instances/{inst.id}/withdraw", json={"reason": "计划变更"})
        assert resp.json()["status"] == "withdrawn"

    def test_withdraw_not_starter(self, client, db):
        from app.core.security import get_current_user
        from app.main import app
        from app.models.user import Role, User

        env = self._passed_env(db)
        inst = helpers.make_instance(db, env["definition"].id, env["contract"].id,
                                     starter_id=42, starter_name="别人")
        db.commit()
        env["contract"].owner_id = 99
        db.commit()
        plain = User(id=99, username="plain", password_hash="x", real_name="普通",
                     roles=[Role(id=98, code="staff", name="员工")])
        app.dependency_overrides[get_current_user] = lambda: plain
        resp = client.post(f"{API}/workflow/instances/{inst.id}/withdraw", json={"reason": "x"})
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "WORKFLOW_ONLY_STARTER_CAN_WITHDRAW"

    def test_withdraw_404(self, client, db):
        resp = client.post(f"{API}/workflow/instances/99999/withdraw", json={"reason": "x"})
        assert resp.status_code == 404

    def test_urge(self, client, db):
        env = self._passed_env(db)
        inst = helpers.make_instance(db, env["definition"].id, env["contract"].id)
        db.commit()
        resp = client.post(f"{API}/workflow/instances/{inst.id}/urge")
        assert resp.status_code == 200
        from app.models.knowledge import Notification

        db.expire_all()
        assert db.query(Notification).filter_by(type="approval_todo").count() == 1

    def test_urge_404(self, client, db):
        assert client.post(f"{API}/workflow/instances/99999/urge").status_code == 404

    def test_list_definitions(self, client, db):
        env = self._passed_env(db)
        resp = client.get(f"{API}/workflow/definitions")
        assert resp.json()[0]["name"] == env["definition"].name

    def test_save_definition_create(self, client, db):
        resp = client.post(f"{API}/workflow/definitions", json={
            "name": "新流程", "contractTypes": ["purchase"],
            "nodes": [{"id": "n1", "type": "approval", "name": "部门经理审批",
                       "signMode": "or", "assignees": ["role:dept_manager"], "timeoutHours": 24}],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["version"] == 1
        node_ids = [n["id"] for n in body["nodes"]]
        assert node_ids == ["start", "n1", "end"]

    def test_save_definition_with_condition(self, client, db):
        resp = client.post(f"{API}/workflow/definitions", json={
            "name": "条件流", "contractTypes": ["purchase"],
            "nodes": [
                {"id": "c1", "type": "condition", "name": "风险分流",
                 "riskThreshold": 80, "amountThreshold": 500000},
                {"id": "n1", "type": "approval", "name": "普通审批", "assignees": ["role:dept_manager"]},
                {"id": "n2", "type": "approval", "name": "加签审批", "assignees": ["role:dept_manager"]},
            ],
        })
        assert resp.status_code == 200
        cond = next(n for n in resp.json()["nodes"] if n["id"] == "c1")
        assert cond["rules"][0]["when"] == "risk_score < 80 or amount >= 500000"
        assert cond["rules"][0]["goto"] == "n1"
        assert cond["rules"][1]["goto"] == "n2"

    def test_save_definition_update(self, client, db):
        env = self._passed_env(db)
        resp = client.post(f"{API}/workflow/definitions", json={
            "id": env["definition"].id, "name": "改名后的流", "contractTypes": ["sales"],
            "nodes": [{"id": "n1", "type": "approval", "name": "审批", "assignees": ["role:dept_manager"]}],
        })
        assert resp.json()["version"] == 2  # immutable edit, version +1

    def test_save_definition_update_404(self, client, db):
        resp = client.post(f"{API}/workflow/definitions", json={
            "id": 99999, "name": "x", "contractTypes": ["purchase"],
            "nodes": [{"id": "n1", "type": "approval", "name": "审批", "assignees": ["role:dept_manager"]}]})
        assert resp.status_code == 404

    def test_save_definition_validation(self, client, db):
        nodes = [{"id": "n1", "type": "approval", "name": "审批", "assignees": ["role:dept_manager"]}]
        assert client.post(f"{API}/workflow/definitions",
                           json={"name": "", "contractTypes": ["purchase"], "nodes": nodes}
                           ).status_code == 400
        assert client.post(f"{API}/workflow/definitions",
                           json={"name": "x", "contractTypes": [], "nodes": nodes}).status_code == 400
        assert client.post(f"{API}/workflow/definitions",
                           json={"name": "x", "contractTypes": ["purchase"], "nodes": []}
                           ).status_code == 400
        resp = client.post(f"{API}/workflow/definitions", json={
            "name": "x", "contractTypes": ["purchase"],
            "nodes": [{"id": "dup", "type": "approval", "name": "a", "assignees": ["role:dept_manager"]},
                      {"id": "dup", "type": "approval", "name": "b", "assignees": ["role:dept_manager"]}]})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "WORKFLOW_DUP_NODE_ID"

    def test_toggle_definition(self, client, db):
        env = self._passed_env(db)
        resp = client.post(f"{API}/workflow/definitions/{env['definition'].id}/toggle")
        assert resp.json()["enabled"] is False

    def test_toggle_definition_404(self, client, db):
        assert client.post(f"{API}/workflow/definitions/99999/toggle").status_code == 404

"""Unit tests for the services layer (part 1): review service / contract management service."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.ai import llm_client
from app.core.exceptions import AppError
from app.services import contract_service, knowledge_service, review_service
from tests import helpers

GRAPH_OUT = {
    "findings": [
        {"clause_no": "第一条", "clause_id": 1, "risk_level": "high", "risk_type": "权责不对等",
         "issue": "单方无限权利", "original_text": "原文", "legal_basis": "《民法典》",
         "suggestion": "建议修订", "suggested_text": "改写", "rag_hits": ["依据"], "source": "rule"},
        {"clause_no": "第二条", "clause_id": 2, "risk_level": "medium", "risk_type": "权责不对等",
         "issue": "AI 参考", "original_text": "原文2", "legal_basis": "-", "suggestion": "建议",
         "suggested_text": None, "rag_hits": [], "source": "llm"},
    ],
    "stats": {"high": 1, "medium": 0, "low": 0, "ai_high": 0, "ai_medium": 1, "ai_low": 0,
              "score": 60, "failed_clauses": 0},
    "opinion": "不建议签署。",
    "tokens": 42,
}


@pytest.fixture()
def review_task_env(db):
    user = helpers.make_user(db)
    contract = helpers.make_contract(db, owner_id=user.id, status="parsed")
    version = helpers.make_version(db, contract.id, parse_status="parsed")
    helpers.make_clause(db, version.id, contract.id, clause_no="第一条", content="付款条。")
    helpers.make_clause(db, version.id, contract.id, clause_no="第二条", content="违约条。")
    task = helpers.make_review_task(db, contract.id, version_id=version.id, status="pending")
    db.commit()
    return {"contract": contract, "version": version, "task": task, "user": user}


def _patch_graph(monkeypatch, out=None, exc=None):
    def fake_graph(db, **kw):
        if exc:
            raise exc
        return out or GRAPH_OUT

    monkeypatch.setattr("app.agents.review_graph.run_review_graph", fake_graph)


# ===================== review_service =====================
class TestReviewService:
    def test_calc_score(self):
        assert review_service.calc_score(0, 0, 0) == 100
        assert review_service.calc_score(1, 1, 1) == 40
        assert review_service.calc_score(3, 0, 0) == 0  # floor at 0

    def test_template_keywords_mapping(self):
        assert review_service._template_keywords("标的与质量") == ["标的", "质量", "质保", "规格"]
        assert review_service._template_keywords("付款") == ["付款", "支付", "价款", "结算"]
        assert review_service._template_keywords("未知模板名") == ["未知模板名"[:4]]

    def test_run_rule_engine_missing_dispute(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id, contract_type="purchase")
        clause = helpers.make_clause(db, 1, contract.id, clause_no="第一条", clause_type="付款",
                                     content="甲方支付价款。")
        findings = review_service.run_rule_engine(db, contract, [clause])
        dispute = [f for f in findings if f["risk_type"] == "条款缺失"]
        assert dispute and dispute[0]["risk_level"] == "high"
        assert "争议解决" in dispute[0]["issue"]

    def test_run_rule_engine_has_dispute_no_finding(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id, contract_type="purchase")
        clause = helpers.make_clause(db, 1, contract.id, clause_no="第一条", clause_type="争议解决",
                                     content="协商不成提交法院诉讼解决。")
        assert review_service.run_rule_engine(db, contract, [clause]) == []

    def test_run_rule_engine_required_template_missing(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id, contract_type="purchase")
        helpers.make_template(db, name="付款", contract_type="purchase", clause_level="required",
                              content="标准付款条款")
        db.commit()
        clause = helpers.make_clause(db, 1, contract.id, clause_no="第一条", clause_type="保密",
                                     content="保密义务。")
        findings = review_service.run_rule_engine(db, contract, [clause])
        missing = [f for f in findings if "缺少必备条款「付款」" in f["issue"]]
        assert missing and missing[0]["risk_level"] == "medium"

    def test_run_rule_engine_optional_template_ignored(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id, contract_type="purchase")
        helpers.make_template(db, name="付款", contract_type="purchase", clause_level="optional",
                              content="标准付款条款")
        db.commit()
        clause = helpers.make_clause(db, 1, contract.id, clause_no="第一条", clause_type="保密",
                                     content="保密义务。")
        findings = review_service.run_rule_engine(db, contract, [clause])
        assert not [f for f in findings if "缺少必备条款" in f["issue"]]

    def test_run_rule_engine_personal_injury_exclusion(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id, contract_type="labor")
        clause = helpers.make_clause(db, 1, contract.id, clause_no="第一条", clause_type="免责",
                                     content="员工人身损害与公司无关，公司概不负责。")
        findings = review_service.run_rule_engine(db, contract, [clause])
        injury = [f for f in findings if f["risk_type"] == "违法无效"]
        assert injury and injury[0]["risk_level"] == "high"
        assert "第五百零六条" in injury[0]["legal_basis"]

    def test_run_rule_engine_penalty_over_30(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id, contract_type="sales")
        clause = helpers.make_clause(db, 1, contract.id, clause_no="第一条", clause_type="违约",
                                     content="违约金为合同总价的 50%。")
        findings = review_service.run_rule_engine(db, contract, [clause])
        penalty = [f for f in findings if f["risk_type"] == "权责不对等" and "50%" in f["issue"]]
        assert penalty and penalty[0]["risk_level"] == "medium"

    def test_run_rule_engine_penalty_under_30_no_finding(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id, contract_type="sales")
        clause = helpers.make_clause(db, 1, contract.id, clause_no="第一条", clause_type="违约",
                                     content="违约金为合同总价的 20%。")
        findings = review_service.run_rule_engine(db, contract, [clause])
        assert not [f for f in findings if "违约金比例" in f["issue"]]

    def test_run_rule_engine_percentage_without_penalty_keyword(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id, contract_type="sales")
        clause = helpers.make_clause(db, 1, contract.id, clause_no="第一条", clause_type="付款",
                                     content="预付款为合同总价的 50%。")
        findings = review_service.run_rule_engine(db, contract, [clause])
        assert not [f for f in findings if "违约金比例" in f["issue"]]

    def test_run_rule_engine_unilateral_power(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id, contract_type="lease")
        clause = helpers.make_clause(db, 1, contract.id, clause_no="第一条", clause_type="解除",
                                     content="甲方有权随时解除合同且不承担任何责任。")
        findings = review_service.run_rule_engine(db, contract, [clause])
        unilateral = [f for f in findings if f["risk_type"] == "权责不对等" and "第四百九十七条" in f["legal_basis"]]
        assert unilateral and unilateral[0]["risk_level"] == "high"
        assert "提前7日书面通知" in unilateral[0]["suggested_text"]

    def test_run_rule_engine_unilateral_interpretation(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id, contract_type="purchase")
        clause = helpers.make_clause(db, 1, contract.id, clause_no="第一条", clause_type="解释",
                                     content="本合同由甲方单方解释。")
        findings = review_service.run_rule_engine(db, contract, [clause])
        unilateral = [f for f in findings if f["risk_type"] == "权责不对等" and "第四百九十七条" in f["legal_basis"]]
        assert unilateral and "友好协商" in unilateral[0]["suggested_text"]

    def test_run_review_completes(self, review_task_env, monkeypatch, db):
        _patch_graph(monkeypatch)
        monkeypatch.setattr(llm_client, "ensure_llm_configured", lambda: None)
        monkeypatch.setattr(llm_client, "current_model", lambda: "deepseek-chat")
        monkeypatch.setattr("app.ai.rag.index_report_summary", lambda *a, **k: "report_9")
        review_service.run_review(db, review_task_env["task"].id)

        db.expire_all()
        task = db.get(type(review_task_env["task"]), review_task_env["task"].id)
        assert task.status == "completed"
        assert task.progress == 100
        assert task.tokens_used == 42
        assert task.model_version == "deepseek-chat"
        assert task.prompt_version == "default-v1"

        from app.models.knowledge import Notification
        from app.models.review import ReviewReport, RiskFinding

        report = db.query(ReviewReport).one()
        assert report.score == 60 and report.high_count == 1
        assert report.es_doc_id == "report_9"
        # report bound to the review target: version + content hash
        assert report.version_id == review_task_env["task"].version_id
        assert report.content_hash == review_service.version_content_hash(db, report.version_id)
        assert report.report_json["summary"] == {
            "high": 1, "medium": 1, "low": 0, "score": 60, "blockingHigh": 1,
            "aiHigh": 0, "aiMedium": 1, "aiLow": 0, "failedClauses": 0,
            "needsReReview": False, "taskType": "full"}
        assert db.query(RiskFinding).count() == 2
        assert db.query(Notification).filter(Notification.type == "review_done").count() == 1
        contract = db.get(type(review_task_env["contract"]), review_task_env["contract"].id)
        assert contract.status == "review_blocked"

    def test_run_review_passed_status(self, review_task_env, monkeypatch, db):
        out = dict(GRAPH_OUT)
        out["stats"] = {"high": 0, "medium": 0, "low": 0, "ai_high": 0, "ai_medium": 0,
                        "ai_low": 0, "score": 100, "failed_clauses": 0}
        _patch_graph(monkeypatch, out=out)
        monkeypatch.setattr(llm_client, "ensure_llm_configured", lambda: None)
        review_service.run_review(db, review_task_env["task"].id)
        db.expire_all()
        contract = db.get(type(review_task_env["contract"]), review_task_env["contract"].id)
        assert contract.status == "review_passed"

    def test_run_review_task_not_found(self, db):
        review_service.run_review(db, 99999)  # silently returns

    def test_run_review_already_claimed(self, review_task_env, db):
        task = review_task_env["task"]
        task.status = "running"
        db.commit()
        review_service.run_review(db, task.id)  # claimed=0 -> skip
        db.expire_all()
        assert db.get(type(task), task.id).status == "running"

    def test_run_review_no_clauses(self, db, monkeypatch):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id, status="parsed")
        version = helpers.make_version(db, contract.id, parse_status="parsed")
        task = helpers.make_review_task(db, contract.id, version_id=version.id, status="pending")
        db.commit()
        monkeypatch.setattr(llm_client, "ensure_llm_configured", lambda: None)
        with pytest.raises(llm_client.LLMError) as ei:
            review_service.run_review(db, task.id)
        assert "未找到可审查的条款" in str(ei.value)
        db.expire_all()
        assert db.get(type(task), task.id).status == "failed"
        assert db.get(type(contract), contract.id).status == "parsed"

    def test_run_review_graph_failure(self, review_task_env, monkeypatch, db):
        _patch_graph(monkeypatch, exc=llm_client.LLMError("模型全挂了"))
        monkeypatch.setattr(llm_client, "ensure_llm_configured", lambda: None)
        with pytest.raises(llm_client.LLMError):
            review_service.run_review(db, review_task_env["task"].id)
        db.expire_all()
        task = db.get(type(review_task_env["task"]), review_task_env["task"].id)
        assert task.status == "failed"
        assert "模型全挂了" in task.error_msg

    def test_run_review_report_index_failure_tolerated(self, review_task_env, monkeypatch, db):
        _patch_graph(monkeypatch)
        monkeypatch.setattr(llm_client, "ensure_llm_configured", lambda: None)
        monkeypatch.setattr("app.ai.rag.index_report_summary",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("es down")))
        review_service.run_review(db, review_task_env["task"].id)  # does not raise
        db.expire_all()
        task = db.get(type(review_task_env["task"]), review_task_env["task"].id)
        assert task.status == "completed"

    def test_run_review_notification_failure_tolerated(self, review_task_env, monkeypatch, db):
        _patch_graph(monkeypatch)
        monkeypatch.setattr(llm_client, "ensure_llm_configured", lambda: None)
        monkeypatch.setattr("app.ai.rag.index_report_summary", lambda *a, **k: None)

        from app.models.knowledge import Notification

        original_add = type(db).add

        def _add(self, obj):
            if isinstance(obj, Notification):
                raise RuntimeError("notify down")
            return original_add(self, obj)

        monkeypatch.setattr(type(db), "add", _add)
        review_service.run_review(db, review_task_env["task"].id)
        db.expire_all()
        task = db.get(type(review_task_env["task"]), review_task_env["task"].id)
        assert task.status == "completed"

    def test_dedup_rule_first_and_prefix(self):
        findings = [
            {"clause_no": "一", "issue": "同一个问题" + "x" * 60, "source": "llm"},
            {"clause_no": "一", "issue": "同一个问题" + "x" * 60, "source": "rule"},
            {"clause_no": "二", "issue": "另一个问题", "source": "llm"},
        ]
        out = review_service._dedup(findings)
        assert len(out) == 2
        assert out[0]["source"] == "rule"  # rule wins

    def test_pick_clauses_full(self, review_task_env, db):
        assert len(review_service._pick_clauses(db, review_task_env["task"])) == 2

    def test_pick_clauses_single(self, review_task_env, db):
        task = review_task_env["task"]
        task.task_type = "clause"
        task.clause_no = "第二条"
        db.commit()
        clauses = review_service._pick_clauses(db, task)
        assert [c.clause_no for c in clauses] == ["第二条"]

    def test_pick_clauses_diff_changed_only(self, review_task_env, db):
        contract, task = review_task_env["contract"], review_task_env["task"]
        # version (v1) is the baseline; new v2: clause 1 unchanged, clause 2 changed
        v2 = helpers.make_version(db, contract.id, version_no=2)
        helpers.make_clause(db, v2.id, contract.id, clause_no="第一条", content="付款条。")
        helpers.make_clause(db, v2.id, contract.id, clause_no="第二条", content="完全不同的违约条。")
        db.commit()
        task.task_type = "diff"
        task.base_version_no = 1
        task.version_id = v2.id
        db.commit()
        clauses = review_service._pick_clauses(db, task)
        assert {c.clause_no for c in clauses} == {"第二条"}  # clause 1 unchanged, clause 2 changed

    def test_pick_clauses_diff_missing_base(self, review_task_env, db):
        task = review_task_env["task"]
        task.task_type = "diff"
        task.base_version_no = 99
        db.commit()
        assert len(review_service._pick_clauses(db, task)) == 2  # no baseline -> full set

    def test_stale_reason(self):
        now = datetime.now()
        assert "仍未开始执行" in review_service.stale_reason(
            _ns("pending", now - timedelta(minutes=11)), now)
        assert "长时间未完成" in review_service.stale_reason(
            _ns("running", now - timedelta(minutes=31)), now)
        assert review_service.stale_reason(_ns("running", now - timedelta(minutes=1)), now) is None
        assert review_service.stale_reason(_ns("completed", now - timedelta(hours=5)), now) is None
        assert review_service.stale_reason(_ns("pending", None), now) is None

    def test_recover_task_rolls_back_contract(self, review_task_env, db):
        contract, task = review_task_env["contract"], review_task_env["task"]
        contract.status = "under_review"
        task.status = "running"
        db.commit()
        review_service.recover_task(db, task, "僵尸任务")
        db.expire_all()
        assert db.get(type(task), task.id).status == "failed"
        assert db.get(type(contract), contract.id).status == "parsed"

    def test_recover_task_keeps_under_review_when_others_running(self, review_task_env, db):
        contract, task = review_task_env["contract"], review_task_env["task"]
        contract.status = "under_review"
        task.status = "running"
        helpers.make_review_task(db, contract.id, status="running")
        db.commit()
        review_service.recover_task(db, task, "僵尸任务")
        db.expire_all()
        assert db.get(type(contract), contract.id).status == "under_review"

    def test_recover_stale_tasks(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id, status="parsing")
        version = helpers.make_version(db, contract.id, parse_status="parsing",
                                       created_at=datetime.now() - timedelta(minutes=40))
        stale_task = helpers.make_review_task(db, contract.id, status="pending",
                                              created_at=datetime.now() - timedelta(minutes=40))
        fresh_task = helpers.make_review_task(db, contract.id, status="running",
                                              created_at=datetime.now() - timedelta(minutes=1))
        db.commit()
        count = review_service.recover_stale_tasks(db)
        assert count == 2
        db.expire_all()
        assert db.get(type(stale_task), stale_task.id).status == "failed"
        assert db.get(type(fresh_task), fresh_task.id).status == "running"
        assert db.get(type(version), version.id).parse_status == "failed"
        assert db.get(type(contract), contract.id).status == "parse_failed"

    def test_recover_stale_tasks_noop(self, review_task_env, db):
        assert review_service.recover_stale_tasks(db) == 0


def _ns(status, created_at):
    from types import SimpleNamespace

    return SimpleNamespace(status=status, created_at=created_at)


# ===================== contract_service =====================
class TestContractService:
    def test_transition_status(self, review_task_env):
        contract = review_task_env["contract"]
        contract.status = "parsed"
        contract_service.transition_status(contract, "under_review")
        assert contract.status == "under_review"
        contract_service.transition_status(contract, "under_review")  # same state returns directly
        assert contract.status == "under_review"

    def test_transition_status_illegal(self, review_task_env):
        contract = review_task_env["contract"]
        contract.status = "draft"
        with pytest.raises(AppError) as ei:
            contract_service.transition_status(contract, "approved")
        assert ei.value.detail["code"] == "CONTRACT_STATUS_TRANSITION"

    def test_gen_contract_no(self, review_task_env, db):
        no = contract_service.gen_contract_no(db)
        assert no.startswith(f"HT-{datetime.now().year}-")
        assert no.endswith("0001")

    def test_gen_contract_no_increment(self, db):
        user = helpers.make_user(db)
        helpers.make_contract(db, owner_id=user.id, contract_no=f"HT-{datetime.now().year}-0007")
        db.commit()
        assert contract_service.gen_contract_no(db).endswith("0008")

    def test_gen_contract_no_bad_suffix(self, db):
        user = helpers.make_user(db)
        helpers.make_contract(db, owner_id=user.id, contract_no=f"HT-{datetime.now().year}-abc")
        db.commit()
        assert contract_service.gen_contract_no(db).endswith("0001")

    def test_build_contract_out_masked(self, review_task_env, db):
        from app.utils.crypto import encrypt_text

        contract = review_task_env["contract"]
        contract.counterparty_id_no_enc = encrypt_text("91110100MA00X0Y0Z0")
        contract.counterparty_phone_enc = encrypt_text("13800000000")
        db.commit()
        out = contract_service.build_contract_out(contract)
        assert out["counterparty"]["idNo"].startswith("911")
        assert "*" in out["counterparty"]["idNo"]
        assert out["counterparty"]["phone"] == "138****0000"
        assert out["createdAt"] == contract.created_at.strftime("%Y-%m-%dT%H:%M:%S")

    def test_get_contract_or_404(self, review_task_env, db):
        assert contract_service.get_contract_or_404(db, review_task_env["contract"].id) is not None
        with pytest.raises(AppError) as ei:
            contract_service.get_contract_or_404(db, 99999)
        assert ei.value.status_code == 404

    def test_create_contract(self, review_task_env, monkeypatch, db):
        submitted = []
        monkeypatch.setattr(contract_service, "submit_parse_task", lambda vid: submitted.append(vid))
        contract = contract_service.create_contract(
            db, owner=review_task_env["user"], file_name="合同.pdf",
            file_bytes=b"%PDF-1.4 fake", title="新采购合同", contract_type="purchase",
            counterparty_name="乙方", amount=500000)
        assert contract.status == "parsing"
        assert contract.current_version == 1
        assert contract.file_sha256
        assert submitted  # parse task submitted
        from app.models.contract import ContractVersion

        versions = db.query(ContractVersion).filter_by(contract_id=contract.id).all()
        assert versions[0].version_no == 1
        assert versions[0].file_path

    def test_create_contract_invalid_type(self, review_task_env, db):
        with pytest.raises(AppError) as ei:
            contract_service.create_contract(db, owner=review_task_env["user"], file_name="a.pdf",
                                             file_bytes=b"x", title="t", contract_type="bad",
                                             counterparty_name="", amount=0)
        assert ei.value.detail["code"] == "CONTRACT_INVALID_TYPE"

    def test_create_contract_bad_extension(self, review_task_env, db):
        with pytest.raises(AppError) as ei:
            contract_service.create_contract(db, owner=review_task_env["user"], file_name="a.txt",
                                             file_bytes=b"x", title="t", contract_type="nda",
                                             counterparty_name="", amount=0)
        assert ei.value.detail["code"] == "FILE_UNSUPPORTED_FORMAT"

    def test_create_contract_idempotent(self, review_task_env, monkeypatch, db):
        monkeypatch.setattr(contract_service, "submit_parse_task", lambda vid: None)
        first = contract_service.create_contract(db, owner=review_task_env["user"], file_name="a.pdf",
                                                 file_bytes=b"same-bytes", title="t",
                                                 contract_type="nda", counterparty_name="", amount=0)
        second = contract_service.create_contract(db, owner=review_task_env["user"], file_name="a.pdf",
                                                  file_bytes=b"same-bytes", title="t",
                                                  contract_type="nda", counterparty_name="", amount=0)
        assert first.id == second.id  # dedupe by same fingerprint

    def test_upload_new_version(self, review_task_env, monkeypatch, db):
        monkeypatch.setattr(contract_service, "submit_parse_task", lambda vid: None)
        contract = contract_service.upload_new_version(
            db, review_task_env["contract"], "修订.pdf", b"%PDF new")
        assert contract.current_version == 2
        assert contract.status == "parsing"

    def test_upload_new_version_archived(self, review_task_env, db):
        review_task_env["contract"].status = "archived"
        db.commit()
        with pytest.raises(AppError) as ei:
            contract_service.upload_new_version(db, review_task_env["contract"], "a.pdf", b"x")
        assert ei.value.detail["code"] == "CONTRACT_ARCHIVED_NO_VERSION"

    def test_retry_parse(self, review_task_env, monkeypatch, db):
        submitted = []
        monkeypatch.setattr(contract_service, "submit_parse_task", lambda vid: submitted.append(vid))
        review_task_env["contract"].status = "parse_failed"
        db.commit()
        contract = contract_service.retry_parse(db, review_task_env["contract"])
        assert contract.status == "parsing"
        assert submitted

    def test_retry_parse_wrong_status(self, review_task_env, db):
        review_task_env["contract"].status = "parsed"
        db.commit()
        with pytest.raises(AppError) as ei:
            contract_service.retry_parse(db, review_task_env["contract"])
        assert ei.value.detail["code"] == "CONTRACT_NO_REPARSE"

    def test_retry_parse_missing_version(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id, status="parse_failed", current_version=9)
        db.commit()
        with pytest.raises(AppError) as ei:
            contract_service.retry_parse(db, contract)
        assert ei.value.detail["code"] == "CONTRACT_CURRENT_VERSION_MISSING"

    def test_archive_contract(self, review_task_env, db):
        review_task_env["contract"].status = "approved"
        db.commit()
        contract = contract_service.archive_contract(db, review_task_env["contract"])
        assert contract.status == "archived"

    def test_archive_contract_not_final(self, review_task_env, db):
        with pytest.raises(AppError) as ei:
            contract_service.archive_contract(db, review_task_env["contract"])
        assert ei.value.detail["code"] == "CONTRACT_ARCHIVE_REQUIRES_FINAL"

    def test_download_existing_file(self, review_task_env, db, storage_root):
        contract = review_task_env["contract"]
        rel = "contracts/1/origin/v1_contract.pdf"
        target = storage_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"%PDF")
        review_task_env["version"].file_path = rel
        db.commit()
        path, fname = contract_service.download_file_path(db, contract)
        assert path == str(target)
        assert fname == review_task_env["version"].file_name

    def test_download_fallback_txt(self, review_task_env, db, storage_root):
        contract = review_task_env["contract"]
        review_task_env["version"].file_path = None
        db.commit()
        path, fname = contract_service.download_file_path(db, contract)
        assert fname == f"{contract.contract_no}_clauses.txt"
        assert "第一条" in storage_root.joinpath(path).read_text(encoding="utf-8")

    def test_download_no_version(self, db):
        from pathlib import Path

        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id, contract_no="HT-2026-7777",
                                         current_version=5)
        db.commit()
        path, fname = contract_service.download_file_path(db, contract)
        assert fname == "HT-2026-7777_clauses.txt"
        assert "HT-2026-7777" in Path(path).read_text(encoding="utf-8")

    def test_contract_dir_file(self, storage_root):
        p = contract_service.contract_dir_file(3, "a.txt")
        assert p.parent.exists()  # directory created
        assert p.name == "a.txt"

    def test_build_version_diff_no_llm(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id)
        v1 = helpers.make_version(db, contract.id, version_no=1)
        v2 = helpers.make_version(db, contract.id, version_no=2)
        helpers.make_clause(db, v1.id, contract.id, clause_no="第一条", content="甲方支付价款一百万元。")
        helpers.make_clause(db, v1.id, contract.id, clause_no="第二条", content="保密义务：双方不得向第三方披露任何商业秘密信息。")
        helpers.make_clause(db, v2.id, contract.id, clause_no="第一条", content="甲方支付价款一百万元。")
        helpers.make_clause(db, v2.id, contract.id, clause_no="第三条", content="交付时间：乙方应在三十日内将货物运抵指定仓库。")
        db.commit()
        items = contract_service.build_version_diff(db, v1, v2, use_llm=False)
        assert {i["kind"] for i in items} == {"removed", "added"}
        assert all("clauseNo" in i for i in items)

    def test_build_version_diff_modified(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id)
        v1 = helpers.make_version(db, contract.id, version_no=1)
        v2 = helpers.make_version(db, contract.id, version_no=2)
        helpers.make_clause(db, v1.id, contract.id, clause_no="第一条", content="甲方支付价款一百万元。")
        helpers.make_clause(db, v2.id, contract.id, clause_no="第一条", content="甲方支付价款二百万元。")
        db.commit()
        items = contract_service.build_version_diff(db, v1, v2, use_llm=False)
        assert len(items) == 1 and items[0]["kind"] == "modified"
        assert "改为" in items[0]["summary"]

    def test_build_version_diff_semantic_match(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id)
        v1 = helpers.make_version(db, contract.id, version_no=1)
        v2 = helpers.make_version(db, contract.id, version_no=2)
        helpers.make_clause(db, v1.id, contract.id, clause_no="第1条", content="甲方支付价款一百万元整。")
        helpers.make_clause(db, v2.id, contract.id, clause_no="第2条", content="甲方支付价款一百零一元整。")
        db.commit()
        items = contract_service.build_version_diff(db, v1, v2, use_llm=False)
        assert len(items) == 1 and items[0]["kind"] == "modified"  # semantic match counts as a modified pair

    def test_build_version_diff_with_llm(self, db, monkeypatch):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id)
        v1 = helpers.make_version(db, contract.id, version_no=1)
        v2 = helpers.make_version(db, contract.id, version_no=2)
        helpers.make_clause(db, v1.id, contract.id, clause_no="第一条", content="甲方支付价款一百万元。")
        helpers.make_clause(db, v2.id, contract.id, clause_no="第一条", content="甲方支付价款二百万元。")
        db.commit()
        monkeypatch.setattr("app.services.diff_llm_service.summarize_diff",
                            lambda old, new: ("drift", "语义漂移"))
        items = contract_service.build_version_diff(db, v1, v2, use_llm=True)
        assert items[0]["kind"] == "drift"
        assert items[0]["summary"] == "语义漂移"

    def test_build_version_diff_identical_skipped(self, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id)
        v1 = helpers.make_version(db, contract.id, version_no=1)
        v2 = helpers.make_version(db, contract.id, version_no=2)
        helpers.make_clause(db, v1.id, contract.id, clause_no="第一条", content="完全相同的内容。")
        helpers.make_clause(db, v2.id, contract.id, clause_no="第一条", content="完全相同的内容。")
        db.commit()
        assert contract_service.build_version_diff(db, v1, v2, use_llm=False) == []

    def test_push_notification(self, db):
        contract_service.push_notification(db, ntype="review_done", title="t", content="c")
        from app.models.knowledge import Notification

        db.expire_all()
        assert db.query(Notification).one().title == "t"

    def test_index_clauses_to_es(self, review_task_env, monkeypatch, db):
        indexed = []
        monkeypatch.setattr(knowledge_service, "bulk_index_contract_clauses",
                            lambda docs: indexed.append(docs))
        contract_service.index_clauses_to_es(db, review_task_env["version"])
        assert indexed and indexed[0][0]["clause_no"] == "第一条"

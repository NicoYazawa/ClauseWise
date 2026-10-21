"""Unit tests for schemas / models / db session."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from app.db.session import get_db
from app.schemas import auth as auth_schema
from app.schemas import common, contract, knowledge, qa, review, system, workflow
from tests import helpers


# ===================== schemas/common =====================
class TestCommon:
    def test_serialize_helpers(self):
        assert common.serialize_dt(None) is None
        assert common.serialize_dt(datetime(2026, 1, 2, 3, 4, 5)) == "2026-01-02T03:04:05"
        assert common.serialize_date(None) is None
        assert common.serialize_date(date(2026, 1, 2)) == "2026-01-02"

    def test_camel_model_alias_roundtrip(self):
        class _M(common.CamelModel):
            user_name: str = ""
            dept_id: int = 0

        m = _M(userName="alice", deptId=3)  # input accepts camelCase
        assert m.user_name == "alice"
        assert m.model_dump(by_alias=True) == {"userName": "alice", "deptId": 3}
        m2 = _M(user_name="bob", dept_id=4)  # also accepts snake_case
        assert m2.user_name == "bob"

    def test_camel_model_from_attributes(self):
        from types import SimpleNamespace

        class _M(common.CamelModel):
            full_name: str = ""

        obj = SimpleNamespace(full_name="张三")
        assert _M.model_validate(obj).full_name == "张三"


# ===================== schemas/auth =====================
class TestAuthSchemas:
    def test_login_request(self):
        r = auth_schema.LoginRequest(username="u", password="p")
        assert r.username == "u"

    def test_change_password_defaults(self):
        r = auth_schema.ChangePasswordRequest()
        assert r.old_password == "" and r.new_password == ""

    def test_user_out_login_at_serializer(self):
        # datetime is formatted as an ISO second-level string via field_serializer (ORM passthrough scenario)
        out = auth_schema.UserOut.model_construct(
            id=1, username="u", real_name="r", dept_name="d", title="t",
            last_login_at=datetime(2026, 1, 1, 8, 0, 0))
        assert out.model_dump()["last_login_at"] == "2026-01-01T08:00:00"

    def test_user_out_login_at_none_and_str(self):
        out = auth_schema.UserOut(id=1, username="u", real_name="r", dept_name="d", title="t",
                                  lastLoginAt=None)
        assert out.model_dump()["last_login_at"] == "-"
        out2 = auth_schema.UserOut(id=1, username="u", real_name="r", dept_name="d", title="t",
                                   lastLoginAt="raw")
        assert out2.model_dump()["last_login_at"] == "raw"

    def test_auth_user_out(self):
        out = auth_schema.AuthUserOut(id=1, username="u", real_name="r", dept_name="d", title="t",
                                      token="t", roleName="管理员")
        assert out.token == "t" and out.role_name == "管理员"

    def test_create_user_and_update_roles(self):
        r = auth_schema.CreateUserRequest(username="u", real_name="r")
        assert r.roles == []
        assert auth_schema.UpdateRolesRequest().roles == []


# ===================== schemas/contract =====================
class TestContractSchemas:
    def test_counterparty_out_alias(self):
        c = contract.CounterpartyOut(idNo="123")
        assert c.id_no == "123"
        assert c.model_dump(by_alias=True)["idNo"] == "123"

    def test_contract_out_serializers(self):
        out = contract.ContractOut.model_construct(
            id=1, contract_no="HT-1", title="t", contract_type="purchase", owner_id=1,
            status="draft", current_version=1, counterparty=contract.CounterpartyOut(),
            created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 2))
        dumped = out.model_dump()
        assert dumped["created_at"] == "2026-01-01T00:00:00"
        assert dumped["updated_at"] == "2026-01-02T00:00:00"
        assert dumped["counterparty"]["name"] == ""

    def test_version_out(self):
        out = contract.VersionOut(id=1, contractId=1, versionNo=1, fileName="f",
                                  parseStatus="parsed", createdAt=None)
        assert out.model_dump(by_alias=True)["createdAt"] is None

    def test_clause_out_defaults(self):
        out = contract.ClauseOut(id=1, versionId=1, contractId=1, clauseNo="第一条",
                                 clauseType="付款", content="c")
        assert out.page_no == 1

    def test_upload_request_defaults(self):
        r = contract.UploadContractRequest(title="t", contractType="purchase")
        assert r.amount == 0 and r.counterparty_name == ""


# ===================== schemas/review =====================
class TestReviewSchemas:
    def test_start_review_defaults(self):
        r = review.StartReviewRequest(contractId=1)
        assert r.task_type == "full" and r.clause_no is None

    def test_resolve_finding_request(self):
        assert review.ResolveFindingRequest(status="accepted").status == "accepted"

    def test_task_out_serializer(self):
        out = review.ReviewTaskOut.model_construct(
            id=1, contract_id=1, task_type="full", status="completed", progress=100,
            created_at=datetime(2026, 5, 5, 12, 0, 0), completed_at=None)
        dumped = out.model_dump()
        assert dumped["created_at"] == "2026-05-05T12:00:00"
        assert dumped["completed_at"] is None

    def test_finding_out(self):
        out = review.RiskFindingOut(id=1, taskId=1, riskLevel="high", riskType="t", issue="i",
                                    source="rule")
        assert out.rag_hits is None

    def test_report_summary_defaults(self):
        s = review.ReportSummaryOut()
        assert (s.high, s.medium, s.low, s.score, s.blockingHigh) == (0, 0, 0, 0, 0)

    def test_report_out_nested(self):
        out = review.ReviewReportOut(id=1, taskId=1, contractId=1, overallOpinion="o")
        assert out.summary.score == 0 and out.findings == []

    def test_progress_out(self):
        assert review.ProgressOut(taskId=1, status="running", progress=50, errorMsg=None).progress == 50


# ===================== schemas/workflow =====================
class TestWorkflowSchemas:
    def test_node_out_alias(self):
        n = workflow.WFNodeOut(id="n1", type="approval", name="审批", signMode="or",
                               timeoutHours=24)
        assert n.sign_mode == "or" and n.timeout_hours == 24

    def test_edge_out_from_alias(self):
        e = workflow.WFEdgeOut(**{"from": "start", "to": "n1"})
        assert e.from_ == "start"

    def test_definition_out(self):
        d = workflow.WorkflowDefinitionOut(id=1, name="流", version=1)
        assert d.contract_types == [] and d.nodes == []

    def test_definition_node_input(self):
        n = workflow.DefinitionNodeInput(id="n1", type="approval", name="审批")
        assert n.assignees == []

    def test_save_definition_request(self):
        r = workflow.SaveDefinitionRequest(name="流")
        assert r.id is None and r.nodes == []

    def test_context_snapshot_out(self):
        s = workflow.ContextSnapshotOut(highRisk=1, riskTotal=3)
        assert s.high_risk == 1 and s.risk_total == 3

    def test_instance_out_serializers(self):
        out = workflow.WorkflowInstanceOut.model_construct(
            id=1, definition_id=1, definition_name="流", definition_version=1, contract_id=1,
            current_node_id="n1", current_node_name="审批", status="running",
            started_at=datetime(2026, 1, 1), finished_at=None)
        dumped = out.model_dump()
        assert dumped["started_at"] == "2026-01-01T00:00:00"
        assert dumped["finished_at"] is None
        assert dumped["records"] == []

    def test_start_approval_request(self):
        r = workflow.StartApprovalRequest(contractId=1, highRisk=2, riskTotal=5)
        assert r.high_risk == 2

    def test_action_and_withdraw(self):
        a = workflow.ActionRequest(action="approve", expectedNodeId="n1")
        assert a.expected_node_id == "n1"
        assert a.action == "approve"
        assert workflow.WithdrawRequest().reason == ""


# ===================== schemas/knowledge =====================
class TestKnowledgeSchemas:
    def test_law_out_date_serializers(self):
        out = knowledge.LawRegulationOut.model_construct(
            id=1, doc_type="law", title="t", content="c",
            effective_date=date(2026, 1, 1), expiry_date=None)
        dumped = out.model_dump()
        assert dumped["effective_date"] == "2026-01-01"
        assert dumped["expiry_date"] is None

    def test_save_law_defaults(self):
        r = knowledge.SaveLawRequest(title="t", content="c")
        assert r.doc_type == "law" and r.status == "active"

    def test_template_out_and_request(self):
        assert knowledge.ContractTemplateOut(id=1, name="n", contractType="purchase",
                                             clauseLevel="optional", content="c").version == 1
        assert knowledge.SaveTemplateRequest(name="n", contractType="purchase",
                                             content="c").clause_level == "optional"

    def test_import_result_out(self):
        assert knowledge.ImportResultOut().imported == 0


# ===================== schemas/system =====================
class TestSystemSchemas:
    def test_role_info_out(self):
        r = system.RoleInfoOut(code="admin", name="管理员")
        assert r.permissions == [] and r.data_scope == "self"

    def test_update_role_permissions_request(self):
        assert system.UpdateRolePermissionsRequest().permissions == []

    def test_audit_detail_and_log_out(self):
        detail = system.AuditDetailOut()
        assert (detail.ip, detail.ua, detail.result) == ("-", "-", "成功")
        log = system.AuditLogOut.model_construct(
            id=1, username="u", action="a", resource_type="t", resource_id="1",
            detail=system.AuditDetailOut(ip="1.1.1.1"), created_at=datetime(2026, 3, 3))
        assert log.model_dump()["created_at"] == "2026-03-03T00:00:00"
        assert log.detail.ip == "1.1.1.1"

    def test_notification_out(self):
        n = system.AppNotificationOut(id=1, type="t", title="ti", content="c")
        assert n.read is False

    def test_model_version_out(self):
        m = system.ModelVersionOut.model_construct(
            id=1, model_name="m", model_type="llm",
            eval_metrics=system.EvalMetricsOut(accuracy=0.9), activated_at=datetime(2026, 4, 4))
        dumped = m.model_dump()
        assert dumped["activated_at"] == "2026-04-04T00:00:00"
        assert dumped["eval_metrics"]["accuracy"] == 0.9

    def test_eval_metrics_out(self):
        assert system.EvalMetricsOut().accuracy == 0.0

    def test_prompt_out_and_requests(self):
        p = system.PromptTemplateOut.model_construct(
            id=1, version="v1", scene="s", content="c", updated_at=datetime(2026, 6, 6))
        assert p.model_dump()["updated_at"] == "2026-06-06T00:00:00"
        assert system.SavePromptRequest().content == ""
        assert system.ExportLogRequest().format == "word"


# ===================== schemas/qa =====================
class TestQaSchemas:
    def test_ask_request(self):
        assert qa.AskRequest(question="q").question == "q"

    def test_citation_and_result(self):
        c = qa.QaCitationOut(kind="law", id=1, title="t", snippet="s", score=0.5)
        assert qa.AskResultOut(answer="a", sessionId=1, citations=[c]).citations[0].kind == "law"
        assert qa.AskResultOut(answer="a", sessionId=1).citations == []


# ===================== models =====================
class TestModels:
    def test_user_defaults_and_roles(self, db):
        u = helpers.make_user(db)
        role = helpers.make_role(db)
        u.roles.append(role)
        db.commit()
        db.expire_all()
        loaded = db.get(type(u), u.id)
        assert loaded.is_active is True
        assert loaded.dept_name == "法务部"
        assert loaded.roles[0].code == "legal"

    def test_contract_defaults(self, db):
        u = helpers.make_user(db)
        c = helpers.make_contract(db, owner_id=u.id)
        db.commit()
        db.expire_all()
        loaded = db.get(type(c), c.id)
        assert loaded.current_version == 1
        assert loaded.amount == 100000
        assert loaded.updated_at is not None

    def test_version_unique_constraint(self, db):
        from sqlalchemy.exc import IntegrityError

        u = helpers.make_user(db)
        c = helpers.make_contract(db, owner_id=u.id)
        helpers.make_version(db, c.id, version_no=1)
        with pytest.raises(IntegrityError):
            helpers.make_version(db, c.id, version_no=1)
            db.commit()
        db.rollback()

    def test_clause_defaults(self, db):
        u = helpers.make_user(db)
        c = helpers.make_contract(db, owner_id=u.id)
        v = helpers.make_version(db, c.id)
        cl = helpers.make_clause(db, v.id, c.id)
        db.commit()
        db.expire_all()
        loaded = db.get(type(cl), cl.id)
        assert loaded.page_no == 1
        assert loaded.version.clauses[0].id == cl.id  # relationship usable

    def test_contract_owner_relationship(self, db):
        u = helpers.make_user(db)
        c = helpers.make_contract(db, owner_id=u.id)
        db.commit()
        db.expire_all()
        loaded = db.get(type(c), c.id)
        assert loaded.owner.username == u.username  # lazy=joined

    def test_review_task_report_relationship(self, db):
        u = helpers.make_user(db)
        c = helpers.make_contract(db, owner_id=u.id)
        t = helpers.make_review_task(db, c.id)
        helpers.make_report(db, t.id, c.id)
        helpers.make_finding(db, t.id)
        db.commit()
        db.expire_all()
        loaded = db.get(type(t), t.id)
        assert loaded.report.task_id == t.id
        assert loaded.findings[0].task_id == t.id
        assert loaded.contract.title == c.title

    def test_workflow_instance_records(self, db):
        u = helpers.make_user(db)
        c = helpers.make_contract(db, owner_id=u.id)
        d = helpers.make_definition(db)
        inst = helpers.make_instance(db, d.id, c.id)
        helpers.make_approval_record(db, inst.id)
        db.commit()
        db.expire_all()
        loaded = db.get(type(inst), inst.id)
        assert loaded.records[0].instance_id == inst.id

    def test_agent_trace_defaults(self, db):
        t = helpers.make_trace(db)
        db.commit()
        db.expire_all()
        loaded = db.get(type(t), t.id)
        assert loaded.step_idx == 0 and loaded.payload == {"k": "v"}

    def test_knowledge_models_defaults(self, db):
        law = helpers.make_law(db)
        tpl = helpers.make_template(db)
        prompt = helpers.make_prompt(db)
        db.commit()
        db.expire_all()
        assert db.get(type(law), law.id).status == "active"
        assert db.get(type(tpl), tpl.id).clause_level == "optional"
        assert db.get(type(prompt), prompt.id).is_active is True

    def test_models_all_exports(self):
        import app.models as m

        assert "User" in m.__all__ and "AgentTrace" in m.__all__


# ===================== db/session =====================
class TestDbSession:
    def test_get_db_yields_and_closes(self):
        gen = get_db()
        session = next(gen)
        assert session is not None
        with pytest.raises(StopIteration):
            next(gen)  # close takes effect in finally

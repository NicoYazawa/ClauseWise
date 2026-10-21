"""API-layer unit tests (part 3): system admin / knowledge base / Q&A / agents / alert callbacks."""
from __future__ import annotations

import io

import pytest

from app.core import security
from tests import helpers

API = "/api/v1"


@pytest.fixture()
def perm_user(db):
    """A real user with admin permissions (for require_perm endpoints)."""
    from app.core import security
    from app.models.user import Permission, Role

    perms = [Permission(code="system:user", name="用户"), Permission(code="system:role", name="角色")]
    role = Role(id=1, code="admin", name="系统管理员", permissions=perms)
    u = helpers.make_user(db, username="root", password_hash=security.hash_password("x"),
                          roles=[role])
    db.commit()
    return u


# ===================== system: users / roles =====================
class TestSystemUsersApi:
    def test_list_users(self, client, db):
        helpers.make_user(db, username="u1")
        helpers.make_user(db, username="u2")
        db.commit()
        assert len(client.get(f"{API}/users").json()) == 2

    def test_create_user(self, client, db, perm_user):
        helpers.make_role(db, code="legal", name="法务")
        db.commit()
        _ = perm_user  # only to establish a logged-in user with admin permissions
        resp = client.post(f"{API}/users", json={
            "username": "newuser", "realName": "新人", "deptName": "法务部",
            "title": "专员", "phone": "13800000000", "roles": ["legal"]})
        assert resp.status_code == 200
        body = resp.json()
        assert body["username"] == "newuser"
        assert body["roles"] == ["legal"]
        db.expire_all()
        from app.models.user import User

        loaded = db.query(User).filter_by(username="newuser").one()
        assert loaded.password_hash  # 初始密码已哈希

    def test_create_user_bad_username(self, client, db, perm_user):
        resp = client.post(f"{API}/users", json={"username": "1bad", "realName": "x", "roles": ["a"]})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "USERNAME_FORMAT"

    def test_create_user_duplicate(self, client, db, perm_user):
        helpers.make_role(db, code="legal", name="法务")
        helpers.make_user(db, username="dup")
        db.commit()
        resp = client.post(f"{API}/users", json={"username": "dup", "realName": "x", "roles": ["legal"]})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "USERNAME_EXISTS"

    def test_create_user_realname_required(self, client, db, perm_user):
        resp = client.post(f"{API}/users", json={"username": "okname", "realName": "  ", "roles": ["a"]})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "USER_REALNAME_REQUIRED"

    def test_create_user_role_required(self, client, db, perm_user):
        resp = client.post(f"{API}/users", json={"username": "okname", "realName": "x", "roles": []})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "USER_ROLE_REQUIRED"

    def test_create_user_invalid_role(self, client, db, perm_user):
        resp = client.post(f"{API}/users", json={"username": "okname", "realName": "x",
                                                 "roles": ["ghost"]})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "USER_INVALID_ROLE"

    def test_reset_password(self, client, db, perm_user):
        # regression: reset password must be a one-time random temporary password; no fixed default (e.g. 123456)
        u = helpers.make_user(db, username="target", password_hash=security.hash_password("OriginalPass123!"))
        db.commit()
        resp = client.post(f"{API}/users/{u.id}/reset-password")
        assert resp.status_code == 200
        temporary = resp.json()["temporaryPassword"]
        assert temporary and temporary != "123456" and len(temporary) >= 20
        db.expire_all()
        loaded = db.get(type(u), u.id)
        assert not security.verify_password("123456", loaded.password_hash)
        assert not security.verify_password("OriginalPass123!", loaded.password_hash)
        assert security.verify_password(temporary, loaded.password_hash)
        assert loaded.must_change_password is True

    def test_reset_password_404(self, client, db, perm_user):
        assert client.post(f"{API}/users/99999/reset-password").status_code == 404

    def test_toggle_user(self, client, db, perm_user):
        u = helpers.make_user(db, username="toggle")
        db.commit()
        resp = client.post(f"{API}/users/{u.id}/toggle")
        assert resp.json()["isActive"] is False
        resp2 = client.post(f"{API}/users/{u.id}/toggle")
        assert resp2.json()["isActive"] is True

    def test_toggle_self_forbidden(self, client, db, perm_user):
        # the current logged-in user is perm_user (id=1) -> disabling self errors
        client.user_state["user_id"] = perm_user.id
        resp = client.post(f"{API}/users/{perm_user.id}/toggle")
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "USER_CANNOT_DISABLE_SELF"

    def test_toggle_user_404(self, client, db, perm_user):
        assert client.post(f"{API}/users/99999/toggle").status_code == 404

    def test_update_user_roles(self, client, db, perm_user):
        helpers.make_role(db, code="boss", name="老板")
        u = helpers.make_user(db, username="roles")
        db.commit()
        resp = client.put(f"{API}/users/{u.id}/roles", json={"roles": ["boss"]})
        assert resp.json()["roles"] == ["boss"]

    def test_update_user_roles_404(self, client, db, perm_user):
        resp = client.put(f"{API}/users/99999/roles", json={"roles": []})
        assert resp.status_code == 404

    def test_list_roles(self, client, db):
        helpers.make_role(db, code="a", permissions=[helpers.make_permission(db, code="p1")])
        db.commit()
        roles = client.get(f"{API}/roles").json()
        assert roles[0]["code"] == "a"
        assert roles[0]["permissions"] == ["p1"]

    def test_update_role_permissions(self, client, db, perm_user):
        helpers.make_permission(db, code="contract:upload")
        helpers.make_permission(db, code="contract:download")
        helpers.make_role(db, code="legal")
        db.commit()
        resp = client.put(f"{API}/roles/legal/permissions",
                          json={"permissions": ["contract:upload", "contract:download"]})
        assert sorted(resp.json()["permissions"]) == ["contract:download", "contract:upload"]

    def test_update_role_permissions_404(self, client, db, perm_user):
        resp = client.put(f"{API}/roles/ghost/permissions", json={"permissions": []})
        assert resp.status_code == 404


# ===================== Privilege-escalation guard (a non-admin holding system:user/role must not escalate) =====================
class TestPrivilegeEscalationGuard:
    def _manager(self, db):
        from app.models.user import Permission

        perms = [Permission(code="system:user", name="用户"), Permission(code="system:role", name="角色")]
        role = helpers.make_role(db, code="hr", name="人事", permissions=perms)
        return helpers.make_user(db, username="hradmin", roles=[role])

    def test_non_admin_cannot_grant_admin_role(self, client, db):
        helpers.make_role(db, code="admin", name="系统管理员")
        manager = self._manager(db)
        target = helpers.make_user(db, username="victim")
        db.commit()
        client.user_state["user_id"] = manager.id
        resp = client.put(f"{API}/users/{target.id}/roles", json={"roles": ["admin"]})
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "PERM_DENIED"
        assert client.post(f"{API}/users", json={
            "username": "newadmin", "realName": "提权", "roles": ["admin"]}).status_code == 403
        db.expire_all()
        assert [r.code for r in target.roles] == []

    def test_non_admin_cannot_modify_admin_role_permissions(self, client, db):
        helpers.make_role(db, code="admin", name="系统管理员")
        manager = self._manager(db)
        db.commit()
        client.user_state["user_id"] = manager.id
        assert client.put(f"{API}/roles/admin/permissions", json={"permissions": ["system:user"]}).status_code == 403

    def test_admin_can_still_grant_admin_role(self, client, db, perm_user):
        target = helpers.make_user(db, username="victim")
        db.commit()
        assert client.put(f"{API}/users/{target.id}/roles", json={"roles": ["admin"]}).status_code == 200
        db.expire_all()
        assert [r.code for r in target.roles] == ["admin"]

    def test_update_user_roles_rejects_unknown_role(self, client, db, perm_user):
        u = helpers.make_user(db, username="victim")
        db.commit()
        resp = client.put(f"{API}/users/{u.id}/roles", json={"roles": ["ghost"]})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "USER_INVALID_ROLE"
        db.expire_all()
        assert [r.code for r in u.roles] == []

    def test_update_role_permissions_rejects_unknown_permission(self, client, db, perm_user):
        helpers.make_role(db, code="legal")
        db.commit()
        resp = client.put(f"{API}/roles/legal/permissions", json={"permissions": ["ghost:perm"]})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "ROLE_INVALID_PERMISSION"


# ===================== system: audit / notifications / models / prompts =====================
class TestSystemAdminApi:
    def test_audit_logs(self, client, db):
        helpers.make_audit_log(db, username="alice", action="login")
        helpers.make_audit_log(db, username="bob", action="contract.upload")
        db.commit()
        assert len(client.get(f"{API}/audit-logs").json()) == 2
        assert len(client.get(f"{API}/audit-logs", params={"username": "alice"}).json()) == 1
        assert len(client.get(f"{API}/audit-logs", params={"action": "upload"}).json()) == 1
        assert client.get(f"{API}/audit-logs", params={"username": "  "}).status_code == 200

    def test_audit_log_detail_defaults(self, client, db):
        from app.models.knowledge import AuditLog

        db.add(AuditLog(user_id=1, username="u", action="login", resource_type="会话",
                        resource_id="-", detail=None, created_at=__import__("datetime").datetime.now()))
        db.commit()
        detail = client.get(f"{API}/audit-logs").json()[0]["detail"]
        assert detail["ip"] == "-" and detail["result"] == "成功"

    def test_notifications_scope(self, client, db):
        helpers.make_notification(db, user_id=None, title="全员通知")
        helpers.make_notification(db, user_id=1, title="给我的")
        helpers.make_notification(db, user_id=2, title="给别人的")
        db.commit()
        client.user_state["user_id"] = 1  # admin_user.id
        titles = [n["title"] for n in client.get(f"{API}/notifications").json()]
        assert set(titles) == {"全员通知", "给我的"}

    def test_mark_notification_read(self, client, db):
        n = helpers.make_notification(db)
        db.commit()
        resp = client.post(f"{API}/notifications/{n.id}/read")
        assert resp.status_code == 200
        db.expire_all()
        assert db.get(type(n), n.id).read is True

    def test_mark_notification_read_missing(self, client, db):
        assert client.post(f"{API}/notifications/99999/read").status_code == 200  # 幂等

    def test_model_versions(self, client, db):
        helpers.make_model_version(db, model_name="m1", eval_metrics={"accuracy": 0.9,
                                                                      "falsePositive": 0.1})
        db.commit()
        out = client.get(f"{API}/model-versions").json()[0]
        assert out["modelName"] == "m1"
        assert out["evalMetrics"]["accuracy"] == 0.9
        assert out["activatedAt"]

    def test_model_versions_default_metrics(self, client, db):
        helpers.make_model_version(db, model_name="m1", eval_metrics=None)
        db.commit()
        out = client.get(f"{API}/model-versions").json()[0]
        assert out["evalMetrics"] == {"accuracy": 0, "falsePositive": 0, "adoptionRate": None}

    def test_set_default_model(self, client, db):
        m1 = helpers.make_model_version(db, model_name="a", model_type="llm", is_default=True)
        m2 = helpers.make_model_version(db, model_name="b", model_type="llm")
        db.commit()
        resp = client.post(f"{API}/model-versions/{m2.id}/default")
        assert resp.json()["isDefault"] is True
        db.expire_all()
        assert db.get(type(m1), m1.id).is_default is False

    def test_set_default_model_404(self, client, db):
        assert client.post(f"{API}/model-versions/99999/default").status_code == 404

    def test_set_default_model_already(self, client, db):
        m = helpers.make_model_version(db, is_default=True)
        db.commit()
        resp = client.post(f"{API}/model-versions/{m.id}/default")
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "MODEL_ALREADY_DEFAULT"

    def test_runtime_info(self, client, monkeypatch):
        from app.ai.providers import ModelEndpoint

        monkeypatch.setattr("app.ai.providers.llm_endpoint", lambda: ModelEndpoint(
            kind="llm", provider="deepseek", base_url="http://gw:4000/v1", api_key="k",
            api_key_env="K", model="contract-review"))
        monkeypatch.setattr("app.ai.providers.embedding_endpoint", lambda: ModelEndpoint(
            kind="embedding", provider="dashscope", base_url="https://x", api_key="k",
            api_key_env="K", model="text-embedding-v4", dimensions=1024))
        monkeypatch.setattr("app.ai.gateway_models.resolve_alias_map",
                            lambda base, key: {"contract-review": {"model": "deepseek-v4", "vendor": "deepseek"}})
        body = client.get(f"{API}/runtime-info").json()
        assert body["llm"]["model"] == "contract-review"
        assert body["llm"]["realModel"] == "deepseek-v4"
        assert body["llm"]["realProvider"] == "deepseek"
        assert body["embedding"]["dimensions"] == 1024

    def test_runtime_info_config_error(self, client, monkeypatch):
        from app.ai.providers import ModelConfigError

        def _boom():
            raise ModelConfigError("厂商未知")

        monkeypatch.setattr("app.ai.providers.llm_endpoint", _boom)
        monkeypatch.setattr("app.ai.providers.embedding_endpoint", _boom)
        body = client.get(f"{API}/runtime-info").json()
        assert body["llm"]["configured"] is False
        assert "厂商未知" in body["llm"]["error"]

    def test_prompts(self, client, db):
        helpers.make_prompt(db, version="v1.0", scene="条款合规审查")
        db.commit()
        out = client.get(f"{API}/prompts").json()[0]
        assert out["version"] == "v1.0"
        assert out["updatedAt"]

    def test_save_prompt_content_bumps_version(self, client, db):
        p = helpers.make_prompt(db, version="v1.3")
        db.commit()
        resp = client.put(f"{API}/prompts/{p.id}/content", json={"content": "新 Prompt 内容"})
        assert resp.json()["version"] == "v1.4"
        db.expire_all()
        assert db.get(type(p), p.id).is_active is True

    def test_save_prompt_content_bad_version_format(self, client, db):
        p = helpers.make_prompt(db, version="vX")
        db.commit()
        resp = client.put(f"{API}/prompts/{p.id}/content", json={"content": "内容"})
        assert resp.json()["version"] == "vX.1"

    def test_save_prompt_content_empty(self, client, db):
        p = helpers.make_prompt(db)
        db.commit()
        resp = client.put(f"{API}/prompts/{p.id}/content", json={"content": "  "})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "PROMPT_CONTENT_EMPTY"

    def test_save_prompt_content_404(self, client, db):
        assert client.put(f"{API}/prompts/99999/content", json={"content": "x"}).status_code == 404

    def test_activate_prompt(self, client, db):
        p1 = helpers.make_prompt(db, version="v1.0", is_active=True)
        p2 = helpers.make_prompt(db, version="v2.0", is_active=False)
        db.commit()
        resp = client.post(f"{API}/prompts/{p2.id}/activate")
        assert resp.json()["isActive"] is True
        db.expire_all()
        assert db.get(type(p1), p1.id).is_active is False  # mutually exclusive within a scene

    def test_activate_prompt_already(self, client, db):
        p = helpers.make_prompt(db, is_active=True)
        db.commit()
        resp = client.post(f"{API}/prompts/{p.id}/activate")
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "PROMPT_ALREADY_ACTIVE"

    def test_activate_prompt_404(self, client, db):
        assert client.post(f"{API}/prompts/99999/activate").status_code == 404


# ===================== knowledge =====================
class TestKnowledgeApi:
    def test_list_laws(self, client, db):
        helpers.make_law(db, title="法条一", hit_count=5)
        helpers.make_law(db, title="法条二", hit_count=1)
        db.commit()
        laws = client.get(f"{API}/laws").json()
        assert laws[0]["title"] == "法条一"  # hits sorted by hit count descending

    def test_save_law_create(self, client, db, monkeypatch):
        submitted = []
        monkeypatch.setattr("app.api.v1.knowledge.submit_index_law_task",
                            lambda lid: submitted.append(lid))
        resp = client.post(f"{API}/laws", json={
            "docType": "law", "title": "民法典", "content": "合同编", "sourceRef": "官网",
            "effectiveDate": "2026-01-01", "expiryDate": "2027-01-01", "status": "active"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["title"] == "民法典"
        assert body["effectiveDate"] == "2026-01-01"
        assert body["vectorized"] is False
        assert submitted

    def test_save_law_update(self, client, db, monkeypatch):
        monkeypatch.setattr("app.api.v1.knowledge.submit_index_law_task", lambda lid: None)
        law = helpers.make_law(db, title="旧标题")
        db.commit()
        resp = client.post(f"{API}/laws", json={
            "id": law.id, "docType": "case", "title": "新标题", "content": "新内容",
            "status": "expired"})
        assert resp.json()["title"] == "新标题"
        assert resp.json()["docType"] == "case"
        assert resp.json()["status"] == "expired"
        assert resp.json()["vectorized"] is False

    def test_save_law_update_invalid_doc_type_kept(self, client, db, monkeypatch):
        monkeypatch.setattr("app.api.v1.knowledge.submit_index_law_task", lambda lid: None)
        law = helpers.make_law(db, doc_type="law")
        db.commit()
        resp = client.post(f"{API}/laws", json={
            "id": law.id, "docType": "bad", "title": "t", "content": "c", "status": "bad"})
        assert resp.json()["docType"] == "law"  # illegal value kept as-is
        assert resp.json()["status"] == "active"

    def test_save_law_update_404(self, client, db):
        resp = client.post(f"{API}/laws", json={"id": 99999, "title": "t", "content": "c"})
        assert resp.status_code == 404

    def test_save_law_fields_required(self, client, db):
        resp = client.post(f"{API}/laws", json={"title": "  ", "content": "c"})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "LAW_FIELDS_REQUIRED"

    def test_mark_expired(self, client, db, monkeypatch):
        monkeypatch.setattr("app.services.knowledge_service.delete_law_from_es", lambda law: None)
        law = helpers.make_law(db, es_doc_id="law_1")
        db.commit()
        resp = client.post(f"{API}/laws/{law.id}/expire")
        assert resp.json()["status"] == "expired"
        assert resp.json()["expiryDate"]

    def test_mark_expired_404(self, client, db):
        assert client.post(f"{API}/laws/99999/expire").status_code == 404

    def test_import_laws(self, client, db, monkeypatch):
        from openpyxl import Workbook

        submitted = []
        monkeypatch.setattr("app.api.v1.knowledge.submit_index_law_task",
                            lambda lid: submitted.append(lid))
        wb = Workbook()
        ws = wb.active
        ws.append(["docType", "title", "content"])
        ws.append(["law", "导入法条一", "内容一"])
        ws.append(["case", "导入案例", "案例内容"])
        buf = io.BytesIO()
        wb.save(buf)
        resp = client.post(f"{API}/laws/import",
                           files={"file": ("laws.xlsx", buf.getvalue(),
                                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        assert resp.status_code == 200
        assert resp.json() == {"imported": 2, "vectorized": 2}
        assert len(submitted) == 2

    def test_import_laws_bad_format(self, client, db):
        resp = client.post(f"{API}/laws/import",
                           files={"file": ("a.txt", b"hello", "text/plain")})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "LAW_IMPORT_FORMAT"

    def test_import_laws_too_large(self, client, db):
        resp = client.post(f"{API}/laws/import",
                           files={"file": ("a.xlsx", b"x" * (10 * 1024 * 1024 + 1),
                                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "LAW_IMPORT_TOO_LARGE"

    def test_import_laws_no_rows(self, client, db):
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.append(["docType", "title", "content"])
        ws.append(["law", "", "内容"])  # no title -> no valid rows
        buf = io.BytesIO()
        wb.save(buf)
        resp = client.post(f"{API}/laws/import",
                           files={"file": ("a.xlsx", buf.getvalue(),
                                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "LAW_IMPORT_NO_ROWS"

    def test_list_templates(self, client, db):
        helpers.make_template(db, name="付款")
        db.commit()
        assert client.get(f"{API}/templates").json()[0]["name"] == "付款"

    def test_save_template_create(self, client, db, monkeypatch):
        monkeypatch.setattr("app.services.knowledge_service.index_template", lambda db, tpl: True)
        resp = client.post(f"{API}/templates", json={
            "name": "新模板", "contractType": "purchase", "clauseLevel": "required",
            "content": "模板内容"})
        assert resp.status_code == 200
        assert resp.json()["version"] == 1

    def test_save_template_fields_required(self, client, db):
        resp = client.post(f"{API}/templates", json={"name": " ", "contractType": "purchase",
                                                     "content": "c"})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "TEMPLATE_FIELDS_REQUIRED"

    def test_save_template_invalid_level(self, client, db):
        resp = client.post(f"{API}/templates", json={"name": "n", "contractType": "purchase",
                                                     "clauseLevel": "bad", "content": "c"})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "TEMPLATE_INVALID_LEVEL"

    def test_save_template_duplicate(self, client, db, monkeypatch):
        monkeypatch.setattr("app.services.knowledge_service.index_template", lambda db, tpl: True)
        helpers.make_template(db, name="重复", contract_type="purchase")
        db.commit()
        resp = client.post(f"{API}/templates", json={"name": "重复", "contractType": "purchase",
                                                     "content": "c"})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "TEMPLATE_DUP_NAME"

    def test_save_template_update(self, client, db, monkeypatch):
        monkeypatch.setattr("app.services.knowledge_service.delete_template_from_es", lambda tpl: None)
        monkeypatch.setattr("app.services.knowledge_service.index_template", lambda db, tpl: True)
        tpl = helpers.make_template(db, version=1)
        db.commit()
        resp = client.post(f"{API}/templates", json={
            "id": tpl.id, "name": "改名", "contractType": "sales", "clauseLevel": "optional",
            "content": "新内容"})
        assert resp.json()["version"] == 2

    def test_save_template_update_404(self, client, db):
        resp = client.post(f"{API}/templates", json={"id": 99999, "name": "n",
                                                     "contractType": "purchase", "content": "c"})
        assert resp.status_code == 404

    def test_delete_template(self, client, db, monkeypatch):
        monkeypatch.setattr("app.services.knowledge_service.delete_template_from_es", lambda tpl: None)
        tpl = helpers.make_template(db)
        db.commit()
        tid = tpl.id
        resp = client.delete(f"{API}/templates/{tid}")
        assert resp.status_code == 200
        from app.models.knowledge import ContractTemplate

        assert db.query(ContractTemplate).filter_by(id=tid).count() == 0

    def test_delete_template_404(self, client, db):
        assert client.delete(f"{API}/templates/99999").status_code == 404


# ===================== qa =====================
class TestQaApi:
    def test_ask(self, client, db, monkeypatch):
        monkeypatch.setattr("app.ai.llm_client.ensure_llm_configured", lambda: None)
        monkeypatch.setattr("app.agents.qa_graph.run_qa_graph",
                            lambda q, **kwargs: {"answer": "答案", "citations": [{"kind": "law", "id": 1,
                                                                       "title": "t", "snippet": "s",
                                                                       "score": 0.9}], "no_hit": False})
        resp = client.post(f"{API}/qa/ask", json={"question": "违约金上限"})
        assert resp.status_code == 200
        assert resp.json()["answer"] == "答案"

    def test_ask_empty(self, client, db):
        resp = client.post(f"{API}/qa/ask", json={"question": "  "})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "QA_EMPTY_QUESTION"

    def test_ask_stream(self, client, db, monkeypatch):
        events = [
            {"type": "citations", "citations": []},
            {"type": "delta", "content": "答"},
            {"type": "_hits", "hits": []},
            {"type": "done"},
        ]
        monkeypatch.setattr("app.ai.llm_client.ensure_llm_configured", lambda: None)
        monkeypatch.setattr("app.agents.qa_graph.stream_qa_graph", lambda q, **kwargs: iter(events))
        resp = client.post(f"{API}/qa/ask/stream", json={"question": "问题"})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert "data: " in resp.text
        assert '"done"' in resp.text

    def test_ask_stream_empty_question(self, client, db):
        resp = client.post(f"{API}/qa/ask/stream", json={"question": ""})
        assert resp.status_code == 400

    def test_ask_stream_error_event(self, client, db, monkeypatch):
        monkeypatch.setattr("app.ai.llm_client.ensure_llm_configured", lambda: None)

        def _boom(q, **kwargs):
            raise RuntimeError("stream down")

        monkeypatch.setattr("app.agents.qa_graph.stream_qa_graph", _boom)
        resp = client.post(f"{API}/qa/ask/stream", json={"question": "问题"})
        assert resp.status_code == 200
        assert '"error"' in resp.text
        assert "模型生成失败" in resp.text


# ===================== agents =====================
class TestAgentsApi:
    def test_list_agents(self, client):
        agents = client.get(f"{API}/agents").json()
        names = {a["name"] for a in agents}
        assert {"qa_router", "review_planner", "rule_auditor", "clause_reviewer"} <= names
        planner = next(a for a in agents if a["name"] == "review_planner")
        assert planner["descKey"] == "data.agentDesc.review_planner"
        assert planner["graph"] == "review_graph"

    def test_trace(self, client, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id)
        task = helpers.make_review_task(db, contract.id)
        helpers.make_trace(db, task_type="review", ref_id=task.id, agent_name="planner", step_idx=0)
        helpers.make_trace(db, task_type="review", ref_id=task.id, agent_name="rule_auditor", step_idx=1)
        db.commit()
        rows = client.get(f"{API}/agents/trace", params={"task_type": "review", "ref_id": task.id}).json()
        assert [r["agentName"] for r in rows] == ["planner", "rule_auditor"]
        assert rows[0]["payload"] == {"k": "v"}

    def test_trace_invalid_type(self, client, db):
        resp = client.get(f"{API}/agents/trace", params={"task_type": "bad"})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "AGENT_INVALID_TASK_TYPE"

    def test_trace_recent(self, client, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id)
        first = helpers.make_review_task(db, contract.id)
        second = helpers.make_review_task(db, contract.id)
        helpers.make_trace(db, ref_id=first.id)
        helpers.make_trace(db, ref_id=second.id)
        db.commit()
        rows = client.get(f"{API}/agents/trace/recent").json()
        assert len(rows) == 2
        assert rows[0]["refId"] == 1  # fetched in reverse, returned in order

    def test_trace_recent_limit(self, client, db):
        user = helpers.make_user(db)
        contract = helpers.make_contract(db, owner_id=user.id)
        for i in range(3):
            task = helpers.make_review_task(db, contract.id)
            helpers.make_trace(db, ref_id=task.id)
        db.commit()
        assert len(client.get(f"{API}/agents/trace/recent", params={"limit": 2}).json()) == 2


# ===================== alerts =====================
class TestAlertsApi:
    def test_ingest_disabled(self, client):
        resp = client.post(f"{API}/alerts/prometheus", json={"alerts": []})
        assert resp.status_code == 503
        assert resp.json()["detail"]["code"] == "ALERT_INGEST_DISABLED"

    def test_ingest_invalid_token(self, client, monkeypatch):
        monkeypatch.setattr("app.api.v1.alerts.settings.alert_ingest_token", "secret")
        resp = client.post(f"{API}/alerts/prometheus?token=wrong", json={"alerts": []})
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "ALERT_INVALID_TOKEN"

    def test_ingest_header_token(self, client, monkeypatch):
        monkeypatch.setattr("app.api.v1.alerts.settings.alert_ingest_token", "secret")
        monkeypatch.setattr("app.api.v1.alerts.notify", lambda *a, **k: True)
        resp = client.post(f"{API}/alerts/prometheus", json={"alerts": []},
                           headers={"X-Alert-Token": "secret"})
        assert resp.status_code == 200
        assert resp.json() == {"received": 0, "sent": 0}

    def test_ingest_firing_and_resolved(self, client, monkeypatch):
        monkeypatch.setattr("app.api.v1.alerts.settings.alert_ingest_token", "secret")
        sent = []
        monkeypatch.setattr("app.api.v1.alerts.notify",
                            lambda title, content, level, key: sent.append((title, level)) or True)
        payload = {"alerts": [
            {"status": "firing", "labels": {"alertname": "HighErrorRate", "severity": "critical"},
             "annotations": {"summary": "错误率飙升", "description": "5xx 比例 12%"},
             "fingerprint": "fp1"},
            {"status": "resolved", "labels": {"alertname": "HighErrorRate"},
             "annotations": {"summary": "已恢复"}, "fingerprint": "fp1"},
            {"status": "firing", "labels": {"severity": "weird"},
             "annotations": {}, "fingerprint": "fp2"},
        ]}
        resp = client.post(f"{API}/alerts/prometheus?token=secret", json=payload)
        assert resp.json() == {"received": 3, "sent": 2}
        assert sent[0] == ("[指标告警] HighErrorRate：错误率飙升", "critical")
        assert sent[1][1] == "warning"  # unknown severity -> warning

    def test_ingest_notify_returns_false(self, client, monkeypatch):
        monkeypatch.setattr("app.api.v1.alerts.settings.alert_ingest_token", "secret")
        monkeypatch.setattr("app.api.v1.alerts.notify", lambda *a, **k: False)
        payload = {"alerts": [{"status": "firing", "labels": {"alertname": "X"},
                               "annotations": {}, "fingerprint": "f"}]}
        assert client.post(f"{API}/alerts/prometheus?token=secret", json=payload).json()["sent"] == 0

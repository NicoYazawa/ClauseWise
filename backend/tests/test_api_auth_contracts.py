"""API-layer unit tests (part 1): authentication / contract management."""
from __future__ import annotations

import pytest

from app.core import security
from app.main import app
from tests import helpers

API = "/api/v1"


@pytest.fixture(autouse=True)
def _clear_login_fails():
    from app.api.v1 import auth

    auth._login_fail.clear()
    yield
    auth._login_fail.clear()


def _login_user(db, username="alice", password="Passw0rd!"):
    u = helpers.make_user(db, username=username, password_hash=security.hash_password(password),
                          real_name="爱丽丝")
    db.commit()
    return u, password


# ===================== auth =====================
class TestAuthApi:
    def test_login_success(self, client, db):
        user, password = _login_user(db)
        resp = client.post(f"{API}/auth/login", json={"username": user.username, "password": password})
        assert resp.status_code == 200
        body = resp.json()
        assert body["token"] and body["username"] == "alice"
        assert body["realName"] == "爱丽丝"
        assert body["lastLoginAt"] != "-"
        from app.models.knowledge import AuditLog

        db.expire_all()
        assert db.query(AuditLog).filter_by(action="login").count() == 1

    def test_login_wrong_password(self, client, db):
        _login_user(db)
        resp = client.post(f"{API}/auth/login", json={"username": "alice", "password": "wrong"})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "AUTH_INVALID_CREDENTIALS"

    def test_login_unknown_user(self, client, db):
        resp = client.post(f"{API}/auth/login", json={"username": "ghost", "password": "x"})
        assert resp.status_code == 400

    def test_login_disabled_user(self, client, db):
        helpers.make_user(db, username="bob", password_hash=security.hash_password("p"),
                          is_active=False)
        db.commit()
        resp = client.post(f"{API}/auth/login", json={"username": "bob", "password": "p"})
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "USER_DISABLED"

    def test_login_lock_after_5_failures(self, client, db):
        user, _ = _login_user(db, username="lockme")
        for _ in range(5):
            client.post(f"{API}/auth/login", json={"username": "lockme", "password": "bad"})
        resp = client.post(f"{API}/auth/login", json={"username": "lockme", "password": "bad"})
        assert resp.status_code == 423
        assert resp.json()["detail"]["code"] == "AUTH_LOCKED"

    def test_login_success_clears_fail_counter(self, client, db):
        from app.api.v1 import auth

        user, password = _login_user(db, username="resetme")
        auth._login_fail["resetme"] = [__import__("time").time()]
        resp = client.post(f"{API}/auth/login", json={"username": "resetme", "password": password})
        assert resp.status_code == 200
        assert "resetme" not in auth._login_fail

    def test_me(self, client):
        resp = client.get(f"{API}/auth/me")
        assert resp.status_code == 200
        body = resp.json()
        assert body["username"] == "admin"
        assert body["roles"] == ["admin"]

    def test_change_password_wrong_old(self, client, db):
        u = helpers.make_user(db, username="cp1", password_hash=security.hash_password("old-pass"))
        db.commit()
        client.user_state["user_id"] = u.id
        resp = client.post(f"{API}/auth/change-password",
                           json={"oldPassword": "bad", "newPassword": "new-pass"})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "AUTH_WRONG_OLD_PASSWORD"

    def test_change_password_too_short(self, client, db):
        u = helpers.make_user(db, username="cp2", password_hash=security.hash_password("old-pass"))
        db.commit()
        client.user_state["user_id"] = u.id
        resp = client.post(f"{API}/auth/change-password",
                           json={"oldPassword": "old-pass", "newPassword": "123"})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "AUTH_PASSWORD_TOO_SHORT"

    def test_change_password_same(self, client, db):
        u = helpers.make_user(db, username="cp3", password_hash=security.hash_password("old-pass"))
        db.commit()
        client.user_state["user_id"] = u.id
        resp = client.post(f"{API}/auth/change-password",
                           json={"oldPassword": "old-pass", "newPassword": "old-pass"})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "AUTH_PASSWORD_SAME"

    def test_change_password_success(self, client, db):
        u = helpers.make_user(db, username="cp4", password_hash=security.hash_password("old-pass"))
        db.commit()
        client.user_state["user_id"] = u.id
        resp = client.post(f"{API}/auth/change-password",
                           json={"oldPassword": "old-pass", "newPassword": "NewPass12345!"})
        assert resp.status_code == 200
        db.expire_all()
        loaded = db.get(type(u), u.id)
        assert security.verify_password("NewPass12345!", loaded.password_hash)


# ===================== contracts =====================
class TestContractsApi:
    _seq = 0

    def _seed(self, db, **kw):
        TestContractsApi._seq += 1
        user = helpers.make_user(db, username=f"owner{TestContractsApi._seq}")
        contract = helpers.make_contract(db, owner_id=user.id, **kw)
        db.commit()
        return contract

    def test_list_contracts(self, client, db):
        self._seed(db, title="采购合同甲")
        self._seed(db, title="销售合同乙")
        resp = client.get(f"{API}/contracts")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_list_contracts_filters(self, client, db):
        self._seed(db, title="采购合同甲", contract_type="purchase", status="parsed")
        self._seed(db, title="销售合同乙", contract_type="sales", status="draft")
        assert len(client.get(f"{API}/contracts", params={"keyword": "采购"}).json()) == 1
        assert len(client.get(f"{API}/contracts", params={"contractType": "sales"}).json()) == 1
        assert len(client.get(f"{API}/contracts", params={"status": "parsed"}).json()) == 1
        assert len(client.get(f"{API}/contracts", params={"keyword": "合同", "contractType": "sales",
                                                          "status": "draft"}).json()) == 1
        assert client.get(f"{API}/contracts", params={"keyword": "  "}).status_code == 200

    def test_get_contract(self, client, db):
        c = self._seed(db)
        resp = client.get(f"{API}/contracts/{c.id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == c.id

    def test_get_contract_404(self, client, db):
        assert client.get(f"{API}/contracts/99999").status_code == 404

    def test_versions(self, client, db):
        c = self._seed(db)
        helpers.make_version(db, c.id, version_no=1)
        helpers.make_version(db, c.id, version_no=2)
        db.commit()
        resp = client.get(f"{API}/contracts/{c.id}/versions")
        assert [v["versionNo"] for v in resp.json()] == [2, 1]  # versions in descending order

    def test_clauses_by_version(self, client, db):
        c = self._seed(db)
        v = helpers.make_version(db, c.id)
        helpers.make_clause(db, v.id, c.id, clause_no="第一条")
        db.commit()
        resp = client.get(f"{API}/contracts/versions/{v.id}/clauses")
        assert resp.json()[0]["clauseNo"] == "第一条"

    def test_clauses_by_contract_version(self, client, db):
        c = self._seed(db)
        v = helpers.make_version(db, c.id)
        helpers.make_clause(db, v.id, c.id, clause_no="第二条")
        db.commit()
        resp = client.get(f"{API}/contracts/{c.id}/versions/{v.id}/clauses")
        assert resp.json()[0]["clauseNo"] == "第二条"

    def test_diff_same_version(self, client, db):
        c = self._seed(db)
        resp = client.get(f"{API}/contracts/{c.id}/versions/diff", params={"base": 1, "target": 1})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "CONTRACT_SAME_VERSION"

    def test_diff_version_not_found(self, client, db):
        c = self._seed(db)
        resp = client.get(f"{API}/contracts/{c.id}/versions/diff", params={"base": 1, "target": 2})
        assert resp.status_code == 404

    def test_diff_not_parsed(self, client, db):
        c = self._seed(db)
        helpers.make_version(db, c.id, version_no=1, parse_status="pending")
        helpers.make_version(db, c.id, version_no=2, parse_status="pending")
        db.commit()
        resp = client.get(f"{API}/contracts/{c.id}/versions/diff", params={"base": 1, "target": 2})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "CONTRACT_VERSIONS_NOT_PARSED"

    def test_diff_ok(self, client, db, monkeypatch):
        c = self._seed(db)
        v1 = helpers.make_version(db, c.id, version_no=1, parse_status="parsed")
        v2 = helpers.make_version(db, c.id, version_no=2, parse_status="parsed")
        helpers.make_clause(db, v1.id, c.id, clause_no="第一条", content="甲方支付价款一百万元。")
        helpers.make_clause(db, v2.id, c.id, clause_no="第一条", content="甲方支付价款二百万元。")
        db.commit()
        resp = client.get(f"{API}/contracts/{c.id}/versions/diff", params={"base": 1, "target": 2})
        assert resp.status_code == 200
        assert resp.json()[0]["kind"] == "modified"

    def test_upload(self, client, db, monkeypatch):
        submitted = []
        monkeypatch.setattr("app.services.contract_service.submit_parse_task",
                            lambda vid: submitted.append(vid))
        resp = client.post(
            f"{API}/contracts/upload",
            data={"title": "新合同", "contractType": "purchase", "counterpartyName": "乙方",
                  "amount": 1000},
            files={"file": ("合同.pdf", b"%PDF-1.4 fake content", "application/pdf")},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["title"] == "新合同"
        assert body["status"] == "parsing"
        assert submitted

    def test_upload_bad_type(self, client, db, monkeypatch):
        monkeypatch.setattr("app.services.contract_service.submit_parse_task", lambda vid: None)
        resp = client.post(
            f"{API}/contracts/upload",
            data={"title": "t", "contractType": "bad"},
            files={"file": ("a.pdf", b"x", "application/pdf")},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "CONTRACT_INVALID_TYPE"

    def test_upload_new_version(self, client, db, monkeypatch):
        c = self._seed(db, status="parsed")
        helpers.make_version(db, c.id, version_no=1, parse_status="parsed")
        db.commit()
        monkeypatch.setattr("app.services.contract_service.submit_parse_task", lambda vid: None)
        resp = client.post(
            f"{API}/contracts/{c.id}/versions",
            files={"file": ("修订.pdf", b"%PDF-2", "application/pdf")},
        )
        assert resp.status_code == 200
        assert resp.json()["currentVersion"] == 2

    def test_upload_new_version_missing_contract(self, client, db, monkeypatch):
        monkeypatch.setattr("app.services.contract_service.submit_parse_task", lambda vid: None)
        resp = client.post(f"{API}/contracts/99999/versions",
                           files={"file": ("a.pdf", b"x", "application/pdf")})
        assert resp.status_code == 404

    def test_retry_parse(self, client, db, monkeypatch):
        c = self._seed(db, status="parse_failed")
        helpers.make_version(db, c.id, version_no=1, parse_status="failed")
        submitted = []
        monkeypatch.setattr("app.services.contract_service.submit_parse_task",
                            lambda vid: submitted.append(vid))
        resp = client.post(f"{API}/contracts/{c.id}/retry-parse")
        assert resp.status_code == 200
        assert resp.json()["status"] == "parsing"
        assert submitted

    def test_retry_parse_404(self, client, db):
        assert client.post(f"{API}/contracts/99999/retry-parse").status_code == 404

    def test_archive(self, client, db):
        c = self._seed(db, status="approved")
        resp = client.post(f"{API}/contracts/{c.id}/archive")
        assert resp.status_code == 200
        assert resp.json()["status"] == "archived"

    def test_archive_not_final(self, client, db):
        c = self._seed(db, status="parsed")
        resp = client.post(f"{API}/contracts/{c.id}/archive")
        assert resp.status_code == 400

    def test_download_original(self, client, db, storage_root):
        c = self._seed(db)
        rel = "contracts/1/origin/v1_c.pdf"
        target = storage_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"%PDF original")
        helpers.make_version(db, c.id, version_no=1, file_path=rel, file_name="v1_c.pdf")
        db.commit()
        resp = client.get(f"{API}/contracts/{c.id}/download")
        assert resp.status_code == 200
        assert resp.content == b"%PDF original"

    def test_download_fallback_txt(self, client, db):
        c = self._seed(db, contract_no="HT-2026-9999")
        v = helpers.make_version(db, c.id, version_no=1, file_path=None)
        helpers.make_clause(db, v.id, c.id, clause_no="第一条", content="条款内容。")
        db.commit()
        resp = client.get(f"{API}/contracts/{c.id}/download")
        assert resp.status_code == 200
        assert "第一条" in resp.content.decode("utf-8")

    def test_download_404(self, client, db):
        assert client.get(f"{API}/contracts/99999/download").status_code == 404

    def test_download_requires_permission(self, client, db):
        # the admin role has all permissions; switch to a permissionless user -> 403
        from app.core.security import get_current_user
        from app.models.user import Role, User

        c = self._seed(db)
        db.commit()
        plain = User(id=99, username="plain", password_hash="x", real_name="普通",
                     roles=[Role(id=98, code="staff", name="员工")])
        app.dependency_overrides[get_current_user] = lambda: plain
        resp = client.get(f"{API}/contracts/{c.id}/download")
        assert resp.status_code == 403

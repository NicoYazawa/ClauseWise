"""Credential lifecycle contracts using real authentication and database writes."""
import jwt
import pytest
from fastapi.testclient import TestClient

from app.core import security
from app.core.config import Settings
from app.db.session import get_db
from app.main import app
from tests import helpers


@pytest.fixture
def auth_env(db, session_factory):
    role = helpers.make_role(db, code="admin", data_scope="all")
    admin = helpers.make_user(db, username="administrator", password_hash=security.hash_password("AdminPass123!"), roles=[role])
    user = helpers.make_user(db, username="employee", password_hash=security.hash_password("UserPass123!"))
    db.commit()

    def connection():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = connection
    client = TestClient(app)
    yield client, admin, user
    client.close()
    app.dependency_overrides.clear()


def login(client, name, password):
    response = client.post("/api/v1/auth/login", json={"username": name, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def test_reset_issues_unique_temporary_password_and_revokes_token(auth_env, db):
    client, admin, user = auth_env
    old_token = login(client, user.username, "UserPass123!")["token"]
    headers = {"Authorization": "Bearer " + login(client, admin.username, "AdminPass123!")["token"]}
    first = client.post(f"/api/v1/users/{user.id}/reset-password", headers=headers)
    second = client.post(f"/api/v1/users/{user.id}/reset-password", headers=headers)
    assert first.status_code == second.status_code == 200
    assert "temporaryPassword" in first.json()
    password = second.json()["temporaryPassword"]
    assert len(password) >= 20 and first.json()["temporaryPassword"] != password
    assert client.get("/api/v1/contracts", headers={"Authorization": "Bearer " + old_token}).status_code == 401
    body = login(client, user.username, password)
    assert body["mustChangePassword"] is True
    token_headers = {"Authorization": "Bearer " + body["token"]}
    assert client.get("/api/v1/contracts", headers=token_headers).status_code == 403
    changed = client.post("/api/v1/auth/change-password", headers=token_headers,
                          json={"oldPassword": password, "newPassword": "UpdatedPass123!"})
    assert changed.status_code == 200
    assert client.get("/api/v1/contracts", headers=token_headers).status_code == 401
    new_login = login(client, user.username, "UpdatedPass123!")
    assert new_login["mustChangePassword"] is False
    assert client.get("/api/v1/contracts", headers={"Authorization": "Bearer " + new_login["token"]}).status_code == 200
    # One-time cleartext secrets must never enter persistent audit details.
    from app.models.knowledge import AuditLog
    assert all(password not in str(entry.detail) for entry in db.query(AuditLog).all())


def test_created_user_gets_temporary_password_once(auth_env, db):
    client, admin, _ = auth_env
    role = helpers.make_role(db, code="employee")
    db.commit()
    headers = {"Authorization": "Bearer " + login(client, admin.username, "AdminPass123!")["token"]}
    response = client.post("/api/v1/users", headers=headers, json={"username": "created", "realName": "Created", "roles": [role.code]})
    assert response.status_code == 200
    assert "temporaryPassword" in response.json()
    user = login(client, "created", response.json()["temporaryPassword"])
    assert user["mustChangePassword"] is True
    listed = client.get("/api/v1/users", headers=headers).json()
    assert all("temporaryPassword" not in entry for entry in listed)


@pytest.mark.parametrize("sub", [None, "not-an-int", "0", "-1"])
def test_malformed_jwt_subject_returns_401(auth_env, sub):
    client, _, _ = auth_env
    token = jwt.encode({"sub": sub, "exp": 4102444800}, security.settings.secret_key, algorithm="HS256")
    assert client.get("/api/v1/contracts", headers={"Authorization": "Bearer " + token}).status_code == 401


@pytest.mark.parametrize("value", ["", "insecure-default-secret", "change_me_random_secret", "short"])
def test_unsafe_secret_is_rejected(value):
    settings = Settings(_env_file=None, secret_key=value)
    assert hasattr(settings, "validate_security"), "startup must enforce secure JWT/encryption settings"
    with pytest.raises(ValueError):
        settings.validate_security()


def test_redis_password_is_url_encoded():
    settings = Settings(_env_file=None, redis_url="redis://cache:6379/0", redis_password="a@:/?#b")
    assert settings.redis_url == "redis://:a%40%3A%2F%3F%23b@cache:6379/0"

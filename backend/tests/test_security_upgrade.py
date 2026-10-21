"""Offline migration and bootstrap checks: no real database credentials or model calls."""
import pytest
from sqlalchemy import create_engine, inspect, text

from app.core import security
from app.db import security_upgrade
from tests import helpers


def test_additive_upgrade_of_existing_user_table_is_idempotent():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE user (id INTEGER PRIMARY KEY, username VARCHAR(64))"))
        connection.execute(text("INSERT INTO user(id, username) VALUES (1, 'existing')"))
    security_upgrade.upgrade_schema(engine)
    security_upgrade.upgrade_schema(engine)
    columns = {item["name"] for item in inspect(engine).get_columns("user")}
    assert {"must_change_password", "token_version"} <= columns
    assert "qa_session" in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.execute(text("SELECT username, must_change_password, token_version FROM user")).one() == ("existing", 0, 0)


def test_legacy_default_accounts_cannot_retain_public_password(db):
    role = helpers.make_role(db, code="admin")
    admin = helpers.make_user(db, username="admin", password_hash=security.hash_password("123456"), roles=[role])
    user = helpers.make_user(db, username="legacy", password_hash=security.hash_password("123456"))
    db.commit()
    with pytest.raises(ValueError):
        security_upgrade.harden_legacy_accounts(db, bootstrap_password="")
    db.rollback()
    security_upgrade.harden_legacy_accounts(db, bootstrap_password="BootstrapPass123!")
    db.expire_all()
    assert security.verify_password("BootstrapPass123!", admin.password_hash)
    assert admin.must_change_password is True
    assert admin.token_version == 1
    assert not security.verify_password("123456", user.password_hash)
    assert user.is_active is False
    security_upgrade.harden_legacy_accounts(db, bootstrap_password="")
    assert admin.token_version == 1  # running twice must not reset migrated credentials


def test_new_seed_requires_explicit_admin_secret(db, monkeypatch):
    import scripts.init_db as initializer
    monkeypatch.setattr(initializer.settings, "bootstrap_admin_password", "")
    with pytest.raises(ValueError):
        initializer.seed()
    from app.models.user import User
    assert db.query(User).count() == 0


def test_permission_upgrade_preserves_custom_roles(db):
    keep = helpers.make_permission(db, code="custom:report")
    custom = helpers.make_role(db, code="custom", permissions=[keep])
    business = helpers.make_role(db, code="business_owner")
    db.commit()
    security_upgrade.sync_permissions(db)
    security_upgrade.sync_permissions(db)
    db.expire_all()
    assert {p.code for p in custom.permissions} == {"custom:report"}
    assert {"workflow:start", "review:rerun"} <= {p.code for p in business.permissions}
    business.permissions = []
    db.commit()
    security_upgrade.sync_permissions(db)
    db.expire_all()
    assert business.permissions == []

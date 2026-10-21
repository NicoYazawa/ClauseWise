"""Preset (demo) accounts: disabled by default, idempotent seeding by switch, revoked on disable, public login-page list endpoint."""
import pytest

from app.core.config import settings
from app.core.preset_accounts import FALLBACK_PASSWORD, PRESET_ACCOUNTS
from app.core.security import hash_password, verify_password
from app.db.security_upgrade import PRESET_ACCOUNTS_KEY, SecurityMigration, seed_preset_accounts
from app.models.user import User
from tests import helpers

DEMO_PASSWORD = "DemoPass123!456"


def _make_roles(db) -> None:
    """All roles used by the preset list (names match the production seed, so the endpoint echoes the Chinese role names)."""
    for code, name in (("legal_manager", "法务主管"), ("legal_reviewer", "法务审查员"),
                       ("business_owner", "业务经办人"), ("auditor", "审计员"),
                       ("dept_manager", "部门经理")):
        helpers.make_role(db, code=code, name=name)
    db.commit()


def _enable(monkeypatch, password: str = DEMO_PASSWORD) -> None:
    monkeypatch.setattr(settings, "preset_accounts_enabled", True)
    monkeypatch.setattr(settings, "preset_account_password", password)


def _preset_users():
    return [account for account in PRESET_ACCOUNTS if "admin" not in account.roles]


def test_disabled_by_default_writes_nothing(db, monkeypatch):
    monkeypatch.setattr(settings, "preset_accounts_enabled", False)
    assert seed_preset_accounts(db) == 0
    assert db.query(User).count() == 0
    assert db.get(SecurityMigration, PRESET_ACCOUNTS_KEY) is None


def test_enabled_seeds_loginable_accounts_without_forced_change(db, monkeypatch):
    _make_roles(db)
    _enable(monkeypatch)
    assert seed_preset_accounts(db) == len(_preset_users())
    db.expire_all()
    # admins are not part of preset seeding (their password is managed by BOOTSTRAP_ADMIN_PASSWORD)
    assert db.query(User).filter(User.username == "admin").first() is None
    for account in _preset_users():
        user = db.query(User).filter(User.username == account.username).one()
        assert verify_password(DEMO_PASSWORD, user.password_hash)
        assert user.must_change_password is False
        assert bool(user.is_active) is account.active
        assert {role.code for role in user.roles} == set(account.roles)


def test_second_run_is_idempotent_and_keeps_tokens(db, monkeypatch):
    _make_roles(db)
    _enable(monkeypatch)
    seed_preset_accounts(db)
    db.expire_all()
    versions = {u.username: u.token_version for u in db.query(User).all()}
    assert seed_preset_accounts(db) == 0
    db.expire_all()
    assert {u.username: u.token_version for u in db.query(User).all()} == versions


def test_password_rotation_rehashes_and_revokes_tokens(db, monkeypatch):
    _make_roles(db)
    _enable(monkeypatch)
    seed_preset_accounts(db)
    db.expire_all()
    before = {u.username: u.token_version for u in db.query(User).all()}
    monkeypatch.setattr(settings, "preset_account_password", "RotatedPass789!xyz")
    assert seed_preset_accounts(db) == len(_preset_users())
    db.expire_all()
    for account in _preset_users():
        user = db.query(User).filter(User.username == account.username).one()
        assert verify_password("RotatedPass789!xyz", user.password_hash)
        assert not verify_password(DEMO_PASSWORD, user.password_hash)
        assert user.token_version > before[account.username]


def test_disabling_switch_revokes_preset_accounts(db, monkeypatch):
    _make_roles(db)
    _enable(monkeypatch)
    seed_preset_accounts(db)
    keeper = helpers.make_user(db, username="custom", password_hash=hash_password("KeepMe123!456"))
    # a preset account whose password was changed to a personal one is treated as a real account; disabling the switch must not harm it
    personal = db.query(User).filter(User.username == "zhangmy").one()
    personal.password_hash = hash_password("PersonalPass123!x")
    db.commit()

    monkeypatch.setattr(settings, "preset_accounts_enabled", False)
    # all accounts in the list still using the demo password are revoked (including historical accounts already disabled in the list)
    assert seed_preset_accounts(db) == len(_preset_users()) - 1
    db.expire_all()
    for account in _preset_users():
        user = db.query(User).filter(User.username == account.username).one()
        if account.username == "zhangmy":
            assert user.is_active is True
            assert verify_password("PersonalPass123!x", user.password_hash)
            continue
        assert user.is_active is False, account.username
        assert user.must_change_password is True, account.username
        assert user.token_version >= 1, account.username
        assert not verify_password(DEMO_PASSWORD, user.password_hash), account.username
    # non-list accounts are unaffected, and the marker is cleared (revocation runs only once)
    assert db.get(User, keeper.id).is_active is True
    assert db.get(SecurityMigration, PRESET_ACCOUNTS_KEY) is None
    assert seed_preset_accounts(db) == 0


def test_invalid_preset_password_aborts_startup(db, monkeypatch):
    _make_roles(db)
    _enable(monkeypatch, password="123456")
    with pytest.raises(ValueError):
        seed_preset_accounts(db)
    assert db.query(User).count() == 0


def test_fresh_seed_enables_preset_accounts_when_switch_on(db, monkeypatch):
    import scripts.init_db as initializer

    monkeypatch.setattr(initializer.settings, "bootstrap_admin_password", "BootstrapPass123!")
    monkeypatch.setattr(initializer.settings, "preset_accounts_enabled", True)
    monkeypatch.setattr(initializer.settings, "preset_account_password", DEMO_PASSWORD)
    initializer.seed()
    db.expire_all()
    admin = db.query(User).filter(User.username == "admin").one()
    assert verify_password("BootstrapPass123!", admin.password_hash)
    assert admin.must_change_password is True
    assert admin.is_active is True
    for account in _preset_users():
        user = db.query(User).filter(User.username == account.username).one()
        assert bool(user.is_active) is account.active
        assert verify_password(DEMO_PASSWORD, user.password_hash)


def test_fresh_seed_leaves_preset_accounts_disabled_by_default(db, monkeypatch):
    import scripts.init_db as initializer

    monkeypatch.setattr(initializer.settings, "bootstrap_admin_password", "BootstrapPass123!")
    monkeypatch.setattr(initializer.settings, "preset_accounts_enabled", False)
    initializer.seed()
    db.expire_all()
    for account in _preset_users():
        user = db.query(User).filter(User.username == account.username).one()
        assert user.is_active is False
        assert user.must_change_password is True


def test_public_endpoint_returns_empty_when_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "preset_accounts_enabled", False)
    response = client.get("/api/v1/auth/preset-accounts")
    assert response.status_code == 200
    assert response.json() == {"enabled": False, "password": None, "accounts": []}


def test_public_endpoint_lists_only_loginable_preset_accounts(client, db, monkeypatch):
    _make_roles(db)
    _enable(monkeypatch)
    seed_preset_accounts(db)
    payload = client.get("/api/v1/auth/preset-accounts").json()
    assert payload["enabled"] is True
    assert payload["password"] == DEMO_PASSWORD
    usernames = [item["username"] for item in payload["accounts"]]
    assert "admin" not in usernames  # admins go through BOOTSTRAP_ADMIN_PASSWORD
    assert "wufa" not in usernames  # disabled historical accounts in the list are not shown
    assert len(usernames) == len([a for a in _preset_users() if a.active])
    assert payload["accounts"][0]["roleName"] == "法务主管"
    assert payload["accounts"][0]["deptName"] == "法务部"


def test_public_endpoint_hides_accounts_whose_password_changed(client, db, monkeypatch):
    _make_roles(db)
    _enable(monkeypatch)
    seed_preset_accounts(db)
    user = db.query(User).filter(User.username == "lihuimin").one()
    user.password_hash = hash_password("PersonalPass123!x")
    db.commit()
    usernames = [item["username"] for item in client.get("/api/v1/auth/preset-accounts").json()["accounts"]]
    assert "lihuimin" not in usernames


def test_fallback_password_satisfies_policy():
    from app.core.security import validate_password

    validate_password(FALLBACK_PASSWORD)  # the built-in demo password must always satisfy the password policy


def test_preset_account_roles_are_declared_in_role_catalog():
    """Role codes in the list must be inside the seed role catalog, otherwise seeding silently skips that account."""
    import scripts.init_db as initializer

    available = {code for code, *_rest in initializer.ROLES}
    declared = {code for account in PRESET_ACCOUNTS for code in account.roles}
    assert declared <= available

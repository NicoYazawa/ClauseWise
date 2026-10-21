"""Idempotent, additive security upgrade; never resets tables or changes encryption keys."""
import secrets
from datetime import datetime

from sqlalchemy import DateTime, String, inspect, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.permissions import PERMISSIONS, UPGRADE_GRANTS
from app.core.security import hash_password, validate_password, verify_password
from app.db.base import Base
from app.models.user import Permission, Role, User


class SecurityMigration(Base):
    __tablename__ = "security_migration"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


def upgrade_schema(engine) -> None:
    """Support existing SQLite/MySQL deployments; create_all alone does not add columns."""
    columns = {column["name"] for column in inspect(engine).get_columns("user")} if inspect(engine).has_table("user") else set()
    if columns:
        for name, declaration in (("must_change_password", "BOOLEAN NOT NULL DEFAULT 0"),
                                  ("token_version", "INTEGER NOT NULL DEFAULT 0")):
            if name not in columns:
                with engine.begin() as connection:
                    connection.execute(text(f"ALTER TABLE `user` ADD COLUMN {name} {declaration}"))
    report_columns = (
        {column["name"] for column in inspect(engine).get_columns("review_report")}
        if inspect(engine).has_table("review_report")
        else set()
    )
    if report_columns:
        for name, declaration in (("version_id", "BIGINT NULL"), ("content_hash", "VARCHAR(64) NULL")):
            if name not in report_columns:
                with engine.begin() as connection:
                    connection.execute(text(f"ALTER TABLE review_report ADD COLUMN {name} {declaration}"))
    # Import registers new tables before metadata creation (also for standalone upgrades).
    import app.models  # noqa: F401
    Base.metadata.create_all(engine)


def migrate_legacy_reports(db) -> None:
    """Legacy reports have no version/content binding, so the corresponding contract content cannot be confirmed -> all flagged "needs re-review", never auto-approved."""
    from app.models.review import ReviewReport

    key = "reports-v1-content-binding"
    if db.get(SecurityMigration, key) is not None:
        return
    for report in db.query(ReviewReport).filter(ReviewReport.content_hash.is_(None)).all():  # type: ignore[arg-type]
        js = dict(report.report_json or {})
        summary = dict(js.get("summary") or {})
        summary["needsReReview"] = True
        summary["needsReReviewReason"] = "历史报告未绑定内容哈希，无法确认对应合同内容，需重新审查"
        js["summary"] = summary
        report.report_json = js
    db.add(SecurityMigration(key=key))
    db.commit()


def sync_permissions(db) -> None:
    permissions = {permission.code: permission for permission in db.query(Permission).all()}
    for code, name, module in PERMISSIONS:
        if code not in permissions:
            permission = Permission(code=code, name=name, module=module)
            db.add(permission)
            permissions[code] = permission
    key = "security-v1-permissions"
    if db.get(SecurityMigration, key) is None:
        for role in db.query(Role).all():
            existing = {permission.code for permission in role.permissions}
            for code in UPGRADE_GRANTS.get(role.code, set()) - existing:
                role.permissions.append(permissions[code])
        db.add(SecurityMigration(key=key))
    db.commit()


PRESET_ACCOUNTS_KEY = "preset-accounts-v1"


def _revoke_preset_accounts(db, marker) -> int:
    """Revoke preset accounts when the switch is off: discard the demo password, disable, invalidate the token.

    Only accounts whose password is still the demo password are handled; accounts whose password was changed to a personal one are treated as real accounts and left enabled.
    """
    from app.core.preset_accounts import PRESET_ACCOUNTS, configured_password

    if marker is None:
        return 0
    password = configured_password()
    revoked = 0
    for account in PRESET_ACCOUNTS:
        if "admin" in account.roles:  # Admin passwords are managed via BOOTSTRAP_ADMIN_PASSWORD and are not revoked
            continue
        user = db.query(User).filter(User.username == account.username).first()
        if user is None or not verify_password(password, user.password_hash):
            continue
        user.password_hash = hash_password(secrets.token_urlsafe(32))
        user.is_active = False
        user.must_change_password = True
        user.token_version += 1
        revoked += 1
    db.delete(marker)  # Remove the marker; revocation runs only once
    db.commit()
    return revoked


def seed_preset_accounts(db, *, password: str | None = None) -> int:
    """Idempotently top-up seed / revoke preset accounts by switch (PRESET_ACCOUNTS_ENABLED).

    - On: accounts in the list exist, are enabled, share one password, and are not forced to change it; existing ones are corrected in place (no duplicate insert);
    - Off: if it was ever on, revoke the accounts (disable + invalidate token) and clear the marker.

    Admin accounts are always skipped (password managed by BOOTSTRAP_ADMIN_PASSWORD). Returns the number of affected accounts.
    """
    from app.core.preset_accounts import PRESET_ACCOUNTS, effective_password

    marker = db.get(SecurityMigration, PRESET_ACCOUNTS_KEY)
    target = effective_password() if password is None else password
    if target is None:
        return _revoke_preset_accounts(db, marker)

    validate_password(target)  # A non-compliant demo password is a security misconfiguration that fails at startup
    roles = {role.code: role for role in db.query(Role).all()}
    touched = 0
    for account in PRESET_ACCOUNTS:
        if "admin" in account.roles:
            continue
        if any(code not in roles for code in account.roles):
            continue  # Role catalog not ready: do not create permissionless accounts (first-time init handled by init_db)
        user = db.query(User).filter(User.username == account.username).first()
        if user is None:
            user = User(
                username=account.username,
                password_hash=hash_password(target),
                must_change_password=False,
                real_name=account.real_name,
                dept_name=account.dept_name,
                title=account.title,
                phone=account.phone,
                is_active=account.active,
                last_login_at=datetime.fromisoformat(account.last_login),
                created_at=datetime(2026, 6, 1),
            )
            user.roles = [roles[code] for code in account.roles]
            db.add(user)
            touched += 1
            continue
        changed = False
        if {role.code for role in user.roles} != set(account.roles):
            user.roles = [roles[code] for code in account.roles]
            changed = True
        if not verify_password(target, user.password_hash):
            user.password_hash = hash_password(target)
            changed = True
        if bool(user.is_active) != account.active:
            user.is_active = account.active
            changed = True
        if user.must_change_password:
            user.must_change_password = False
            changed = True
        if changed:
            user.token_version += 1  # Invalidate prior sessions after a password/status change
            touched += 1
    if marker is None:
        db.add(SecurityMigration(key=PRESET_ACCOUNTS_KEY))
    db.commit()
    return touched


def harden_legacy_accounts(db, *, bootstrap_password: str) -> None:
    key = "security-v1-default-credentials"
    if db.get(SecurityMigration, key) is not None:
        return
    weak = [user for user in db.query(User).all() if verify_password("123456", user.password_hash)]
    admins = [user for user in weak if any(role.code == "admin" for role in user.roles)]
    if admins:
        validate_password(bootstrap_password)
    for user in weak:
        is_admin = user in admins
        user.password_hash = hash_password(bootstrap_password if is_admin else secrets.token_urlsafe(32))
        user.must_change_password = True
        user.token_version += 1
        if not is_admin:
            user.is_active = False
    db.add(SecurityMigration(key=key))
    db.commit()

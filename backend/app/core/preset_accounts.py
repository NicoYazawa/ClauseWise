"""Preset (demo) account list: one shared definition used by both seed init and startup top-up seeding.

Off by default (``PRESET_ACCOUNTS_ENABLED=false``). When enabled:

- accounts in the list all use ``PRESET_ACCOUNT_PASSWORD`` (empty falls back to the built-in demo password);
- no forced first login password change; the login page can one-click fill, convenient for demos / trials;
- admin accounts are excluded; their password is still managed by ``BOOTSTRAP_ADMIN_PASSWORD``.

Keep it off in production: when off, startup revokes these accounts (disabled + token invalidated) to avoid leaving demo passwords around.
"""
from typing import NamedTuple

from app.core.config import settings

# Built-in demo password used when PRESET_ACCOUNT_PASSWORD is not explicitly configured.
# Must satisfy validate_password: >=12 chars, <=72 UTF-8 bytes, >=4 distinct characters.
FALLBACK_PASSWORD = "ClauseWise@2026Demo"


class PresetAccount(NamedTuple):
    username: str
    real_name: str
    dept_name: str
    title: str
    phone: str
    roles: tuple[str, ...]
    active: bool
    last_login: str


# Covers all platform roles to demo full flows per identity; active=False accounts are kept only as historical (offboarded) data.
PRESET_ACCOUNTS: tuple[PresetAccount, ...] = (
    PresetAccount("admin", "陈志远", "信息管理部", "系统管理员", "138****0001",
                  ("admin",), True, "2026-08-28T08:00:00"),
    PresetAccount("lihuimin", "李慧敏", "法务部", "法务主管", "138****0002",
                  ("legal_manager",), True, "2026-08-28T09:15:00"),
    PresetAccount("zhangmy", "张明远", "法务部", "法务审查员", "138****0003",
                  ("legal_reviewer",), True, "2026-08-28T09:00:00"),
    PresetAccount("wangxd", "王晓东", "采购部", "业务经办人", "138****0004",
                  ("business_owner",), True, "2026-08-27T17:40:00"),
    PresetAccount("zhaojg", "赵建国", "审计部", "审计员", "138****0005",
                  ("auditor",), True, "2026-08-27T15:20:00"),
    PresetAccount("sunqian", "孙倩", "法务部", "法务审查员", "138****0006",
                  ("legal_reviewer",), True, "2026-08-26T11:30:00"),
    PresetAccount("liuyang", "刘洋", "销售部", "业务经办人", "138****0007",
                  ("business_owner",), True, "2026-08-28T08:45:00"),
    PresetAccount("zhouwm", "周伟民", "采购部", "部门经理", "138****0008",
                  ("dept_manager",), True, "2026-08-27T10:00:00"),
    PresetAccount("wufa", "吴桐", "法务部", "法务主管", "138****0009",
                  ("legal_manager", "legal_reviewer"), False, "2026-06-30T14:00:00"),
)


def configured_password() -> str:
    """The configured demo password (switch-independent): used during revocation to identify accounts still using the demo password."""
    return settings.preset_account_password or FALLBACK_PASSWORD


def effective_password() -> str | None:
    """Returns the active password when the switch is on; returns None when off (meaning the feature is fully disabled)."""
    if not settings.preset_accounts_enabled:
        return None
    return configured_password()

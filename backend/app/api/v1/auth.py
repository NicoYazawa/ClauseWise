"""Auth endpoints: login / change password / current user."""
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from app.core.exceptions import AppError
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.request_ctx import client_info as _client_info
from app.core.security import create_access_token, get_current_user, hash_password, validate_password, verify_password
from app.db.session import get_db
from app.models.user import Role, User
from app.schemas.auth import ChangePasswordRequest, LoginRequest
from app.utils.mask import mask_phone

router = APIRouter(prefix="/auth", tags=["Auth"])

# Simple login-failure lock: 5 fails -> 15-min lock (in-memory, lost on restart)
_login_fail: dict[str, list] = {}


def _user_to_out(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "realName": u.real_name,
        "deptName": u.dept_name,
        "title": u.title,
        "phone": mask_phone(u.phone),
        "roles": [r.code for r in u.roles],
        "isActive": bool(u.is_active),
        "mustChangePassword": bool(u.must_change_password),
        "lastLoginAt": u.last_login_at.strftime("%Y-%m-%dT%H:%M:%S") if u.last_login_at else "-",
    }


def check_lock(username: str) -> None:
    import time

    fails = [t for t in _login_fail.get(username, []) if time.time() - t < 900]
    _login_fail[username] = fails
    if len(fails) >= 5:
        raise AppError("AUTH_LOCKED", 423, "密码错误次数过多，账号已临时锁定 15 分钟")


def record_fail(username: str) -> None:
    import time

    _login_fail.setdefault(username, []).append(time.time())


@router.post("/login", response_model=None)
def login(payload: LoginRequest, request: Request, db: Annotated[Session, Depends(get_db)]):
    ip, ua = _client_info(request)
    check_lock(payload.username)
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        if user:
            record_fail(payload.username)
        write_audit(
            db, user_id=user.id if user else None, username=payload.username, action="login",
            resource_type="会话", resource_id="-", ip=ip, ua=ua, result="失败",
            extra="用户名或密码错误",
        )
        raise AppError("AUTH_INVALID_CREDENTIALS", 400, "用户名或密码错误")
    if not user.is_active:
        write_audit(
            db, user_id=user.id, username=user.username, action="login", resource_type="会话",
            resource_id="-", ip=ip, ua=ua, result="失败", extra="账号已停用",
        )
        raise AppError("USER_DISABLED", 403, "账号已停用，请联系系统管理员")
    _login_fail.pop(payload.username, None)
    user.last_login_at = datetime.now()
    db.commit()
    write_audit(db, user_id=user.id, username=user.username, action="login", resource_type="会话",
                resource_id="-", ip=ip, ua=ua, result="成功")
    token = create_access_token(user.id, user.username, user.token_version)
    role_name = user.roles[0].name if user.roles else ""
    out = _user_to_out(user)
    out["token"] = token
    out["roleName"] = role_name
    return out


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    ip, ua = _client_info(request)
    if not verify_password(payload.old_password, user.password_hash):
        raise AppError("AUTH_WRONG_OLD_PASSWORD", 400, "原密码不正确")
    if payload.new_password == payload.old_password:
        raise AppError("AUTH_PASSWORD_SAME", 400, "新密码不能与原密码相同")
    try:
        validate_password(payload.new_password)
    except ValueError as error:
        raise AppError("AUTH_PASSWORD_TOO_SHORT", 400, str(error)) from error
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    user.token_version += 1
    db.commit()
    write_audit(db, user_id=user.id, username=user.username, action="system.password.change",
                resource_type="会话", resource_id=user.username, ip=ip, ua=ua,
                extra="个人修改密码（新密码不落日志）")
    return {"message": "密码修改成功"}


@router.get("/me")
def me(user: Annotated[User, Depends(get_current_user)]):
    return _user_to_out(user)


@router.get("/preset-accounts", response_model=None)
def preset_accounts(db: Annotated[Session, Depends(get_db)]):
    """Preset (demo) account list for the login page (publicly accessible without login).

    Returned only when ``PRESET_ACCOUNTS_ENABLED`` is on; the password is a shared demo password and is public information.
    Returns an empty list when off, so production never exposes any account or password.
    Admin accounts are excluded here (their password is managed by BOOTSTRAP_ADMIN_PASSWORD).
    """
    from app.core.preset_accounts import PRESET_ACCOUNTS, effective_password

    password = effective_password()
    if password is None:
        return {"enabled": False, "password": None, "accounts": []}
    users = {
        user.username: user
        for user in db.query(User).filter(User.username.in_([a.username for a in PRESET_ACCOUNTS])).all()
    }
    role_names = {role.code: role.name for role in db.query(Role).all()}
    accounts = []
    for account in PRESET_ACCOUNTS:
        if "admin" in account.roles or not account.active:
            continue
        user = users.get(account.username)
        # Only show accounts that are actually enabled and still use the demo password, to avoid login failures after one-click fill
        if user is None or not user.is_active or not verify_password(password, user.password_hash):
            continue
        accounts.append({
            "username": account.username,
            "realName": account.real_name,
            "deptName": account.dept_name,
            "title": account.title,
            "roleCode": account.roles[0],
            "roleName": role_names.get(account.roles[0], ""),
        })
    return {"enabled": True, "password": password, "accounts": accounts}

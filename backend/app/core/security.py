"""Auth & RBAC (design doc 3.5): JWT HS256 + bcrypt + require_perm dependency injection."""
from datetime import UTC, datetime, timedelta
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends, Request
from app.core.exceptions import AppError
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.user import User

_bearer = HTTPBearer(auto_error=False)

# ===================== Password =====================


def validate_password(plain: str) -> None:
    if not (12 <= len(plain) and len(plain.encode("utf-8")) <= 72) or len(set(plain)) < 4:
        raise ValueError("密码须至少 12 字符、至多 72 UTF-8 字节，且不能是简单重复字符")


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("ascii")


def verify_password(plain: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("ascii"))
    except ValueError:
        return False


# ===================== JWT =====================


def create_access_token(user_id: int, username: str, token_version: int = 0) -> str:
    settings.validate_security()
    expire = datetime.now(UTC) + timedelta(days=settings.access_token_expire_days)
    payload = {"sub": str(user_id), "username": username, "exp": expire, "ver": token_version}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as e:
        raise AppError("AUTH_TOKEN_EXPIRED", 401, "登录已过期，请重新登录") from e
    except jwt.InvalidTokenError as e:
        raise AppError("AUTH_INVALID_TOKEN", 401, "无效的身份凭证") from e


# ===================== Dependency injection =====================


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Session, Depends(get_db)],
    request: Request = None,
) -> User:
    if credentials is None:
        raise AppError("AUTH_MISSING_TOKEN", 401, "未登录或缺少 Token")
    payload = decode_token(credentials.credentials)
    try:
        user_id = int(payload["sub"])
        if user_id <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError) as e:
        raise AppError("AUTH_INVALID_TOKEN", 401, "无效的身份凭证") from e
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise AppError("AUTH_ACCOUNT_DISABLED", 401, "账号不存在或已停用")
    if payload.get("ver", 0) != user.token_version:
        raise AppError("AUTH_TOKEN_REVOKED", 401, "登录凭证已撤销，请重新登录")
    if user.must_change_password and (request is None or request.url.path not in (
        "/api/v1/auth/change-password", "/api/v1/auth/me",
    )):
        raise AppError("AUTH_PASSWORD_CHANGE_REQUIRED", 403, "请先修改临时密码")
    return user


def get_user_permissions(user: User) -> set[str]:
    perms: set[str] = set()
    for role in user.roles:
        for p in role.permissions:
            perms.add(p.code)
    return perms


def has_perm(user: User, code: str) -> bool:
    """Whether the user holds the permission point (admin role is always all-power)."""
    if "admin" in {r.code for r in user.roles}:
        return True
    return code in get_user_permissions(user)


def ensure_perm(user: User, code: str, message: str | None = None) -> None:
    """Secondary authorization inside a handler.

    Used when one endpoint triggers another capability that isn't covered by the endpoint's primary
    permission point (e.g. accepting a finding suggestion writes a new version + amended DOCX, which is
    contract write capability and must therefore be checked against contract:upload).
    """
    if not has_perm(user, code):
        raise AppError("PERM_DENIED", 403, message or f"无操作权限：{code}")


def require_perm(code: str):
    """Single-permission-point check dependency: require_perm("contract:download")."""

    def checker(user: Annotated[User, Depends(get_current_user)]) -> User:
        if not has_perm(user, code):
            raise AppError("PERM_DENIED", 403, f"无操作权限：{code}")
        return user

    return checker


def require_any_perm(*codes: str):
    def checker(user: Annotated[User, Depends(get_current_user)]) -> User:
        if "admin" in {r.code for r in user.roles} or get_user_permissions(user).intersection(codes):
            return user
        raise AppError("PERM_DENIED", 403, "无操作权限")
    return checker

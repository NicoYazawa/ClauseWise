"""System admin endpoints: users / roles / audit logs / notifications / model versions / Prompt templates."""
import re
import secrets
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from app.core.exceptions import AppError
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.permissions import PERMISSIONS
from app.core.request_ctx import client_info as _client_info
from app.core.security import get_current_user, hash_password, require_perm, require_any_perm
from app.db.session import get_db
from app.models.knowledge import AuditLog, ModelVersion, Notification, PromptTemplate
from app.models.user import Permission, Role, User
from app.schemas.auth import (
    AuthUserOut,  # noqa: F401
    CreateUserRequest,
    UpdateRolesRequest,
)
from app.schemas.system import (
    SavePromptRequest,
    UpdateRolePermissionsRequest,
)
from app.utils.mask import mask_phone

router = APIRouter(tags=["System Admin"])

_USERNAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{2,31}$")


def _user_out(u: User) -> dict:
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


def _is_admin(operator: User) -> bool:
    return "admin" in {r.code for r in operator.roles}


def _ensure_admin_grantable(operator: User, role_codes: list[str]) -> None:
    """Privilege-escalation guard: only admins may assign the admin role."""
    if "admin" in (role_codes or []) and not _is_admin(operator):
        raise AppError("PERM_DENIED", 403, "仅管理员可授予 admin 角色")


# ===================== User management =====================


@router.get("/users")
def fetch_users(db: Annotated[Session, Depends(get_db)], _: Annotated[User, Depends(require_perm("system:user"))]):
    users = db.query(User).order_by(User.id).all()
    return [_user_out(u) for u in users]


@router.post("/users")
def create_user(
    payload: CreateUserRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    operator: Annotated[User, Depends(require_perm("system:user"))],
):
    ip, ua = _client_info(request)
    if not _USERNAME_RE.match(payload.username or ""):
        raise AppError("USERNAME_FORMAT", 400, "登录名需以字母开头，3~32 位字母/数字/下划线")
    if db.query(User).filter(User.username == payload.username).first():
        raise AppError("USERNAME_EXISTS", 400, "登录名已存在")
    if not (payload.real_name or "").strip():
        raise AppError("USER_REALNAME_REQUIRED", 400, "请填写姓名")
    if not payload.roles:
        raise AppError("USER_ROLE_REQUIRED", 400, "请至少分配一个角色")
    _ensure_admin_grantable(operator, payload.roles)
    roles = db.query(Role).filter(Role.code.in_(payload.roles)).all()
    if len(roles) != len(set(payload.roles)):
        raise AppError("USER_INVALID_ROLE", 400, "存在非法角色")
    temporary_password = secrets.token_urlsafe(24)
    user = User(
        username=payload.username,
        password_hash=hash_password(temporary_password),
        real_name=payload.real_name.strip(),
        dept_name=payload.dept_name or "未分配",
        title=payload.title or "职员",
        phone=payload.phone or None,
        is_active=True,
        must_change_password=True,
        created_at=datetime.now(),
    )
    user.roles = roles
    db.add(user)
    db.commit()
    db.refresh(user)
    write_audit(
        db, user_id=operator.id, username=operator.username, action="system.user.create",
        resource_type="用户", resource_id=user.username, ip=ip, ua=ua,
        extra=f"新建账号（角色：{', '.join(payload.roles)}），已生成一次性临时密码，首次登录须更改",
    )
    return {**_user_out(user), "temporaryPassword": temporary_password}


@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    operator: Annotated[User, Depends(require_perm("system:user"))],
):
    ip, ua = _client_info(request)
    user = db.get(User, user_id)
    if not user:
        raise AppError("USER_NOT_FOUND", 404, "用户不存在")
    temporary_password = secrets.token_urlsafe(24)
    user.password_hash = hash_password(temporary_password)
    user.must_change_password = True
    user.token_version += 1
    db.commit()
    write_audit(db, user_id=operator.id, username=operator.username, action="system.user.resetPwd",
                resource_type="用户", resource_id=user.username, ip=ip, ua=ua,
                extra="已生成一次性临时密码并撤销原登录凭证")
    return {**_user_out(user), "temporaryPassword": temporary_password}


@router.post("/users/{user_id}/toggle")
def toggle_user(
    user_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    operator: Annotated[User, Depends(require_perm("system:user"))],
):
    ip, ua = _client_info(request)
    user = db.get(User, user_id)
    if not user:
        raise AppError("USER_NOT_FOUND", 404, "用户不存在")
    if user.id == operator.id and user.is_active:
        raise AppError("USER_CANNOT_DISABLE_SELF", 400, "不能停用自己的账号")
    user.is_active = not user.is_active
    user.token_version += 1
    db.commit()
    db.refresh(user)
    write_audit(
        db, user_id=operator.id, username=operator.username,
        action="system.user.enable" if user.is_active else "system.user.disable",
        resource_type="用户", resource_id=user.username, ip=ip, ua=ua,
        extra="账号启用" if user.is_active else "离职账号停用（数据保留 ≥ 3 年）",
    )
    return _user_out(user)


@router.put("/users/{user_id}/roles")
def update_user_roles(
    user_id: int,
    payload: UpdateRolesRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    operator: Annotated[User, Depends(require_perm("system:user"))],
):
    ip, ua = _client_info(request)
    user = db.get(User, user_id)
    if not user:
        raise AppError("USER_NOT_FOUND", 404, "用户不存在")
    _ensure_admin_grantable(operator, payload.roles)
    roles = db.query(Role).filter(Role.code.in_(payload.roles)).all()
    if len(roles) != len(set(payload.roles or [])):
        raise AppError("USER_INVALID_ROLE", 400, "存在非法角色")
    user.roles = roles
    db.commit()
    db.refresh(user)
    write_audit(db, user_id=operator.id, username=operator.username, action="system.user.roles",
                resource_type="用户", resource_id=user.username, ip=ip, ua=ua,
                extra=f"角色调整为：{', '.join(payload.roles)}")
    return _user_out(user)


# ===================== Role management =====================


@router.get("/roles")
def fetch_roles(db: Annotated[Session, Depends(get_db)], _: Annotated[User, Depends(require_any_perm("system:user", "system:role"))]):
    roles = db.query(Role).order_by(Role.id).all()
    return [
        {
            "code": r.code,
            "name": r.name,
            "description": r.description,
            "permissions": sorted(p.code for p in r.permissions),
            "dataScope": r.data_scope,
        }
        for r in roles
    ]


@router.put("/roles/{code}/permissions")
def update_role_permissions(
    code: str,
    payload: UpdateRolePermissionsRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    operator: Annotated[User, Depends(require_perm("system:role"))],
):
    ip, ua = _client_info(request)
    role = db.query(Role).filter(Role.code == code).first()
    if not role:
        raise AppError("ROLE_NOT_FOUND", 404, "角色不存在")
    if role.code == "admin" and not _is_admin(operator):
        raise AppError("PERM_DENIED", 403, "仅管理员可修改 admin 角色权限")
    requested = list(dict.fromkeys(payload.permissions or []))
    unknown = [c for c in requested if c not in {p_code for p_code, _n, _m in PERMISSIONS}]
    if unknown:
        raise AppError("ROLE_INVALID_PERMISSION", 400, f"存在非法权限码：{', '.join(unknown)}")
    perms = db.query(Permission).filter(Permission.code.in_(requested)).all()
    if len(perms) != len(requested):
        raise AppError("ROLE_INVALID_PERMISSION", 400, "存在未注册的权限码，请先执行安全升级同步权限目录")
    role.permissions = perms
    db.commit()
    db.refresh(role)
    write_audit(db, user_id=operator.id, username=operator.username, action="system.role.update",
                resource_type="角色", resource_id=role.code, ip=ip, ua=ua,
                extra=f"权限调整为：{', '.join(payload.permissions) or '（空）'}")
    return {
        "code": role.code,
        "name": role.name,
        "description": role.description,
        "permissions": sorted(p.code for p in role.permissions),
        "dataScope": role.data_scope,
    }


# ===================== Audit logs =====================


@router.get("/audit-logs")
def fetch_audit_logs(
    username: str | None = None,
    action: str | None = None,
    db: Annotated[Session, Depends(get_db)] = None,
    _: Annotated[User, Depends(require_perm("system:audit"))] = None,
):
    q = db.query(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    if username and username.strip():
        q = q.filter(AuditLog.username.contains(username.strip()))
    if action and action.strip():
        q = q.filter(AuditLog.action.contains(action.strip()))
    logs = q.limit(500).all()
    out = []
    for lg in logs:
        detail = dict(lg.detail or {})
        out.append(
            {
                "id": lg.id,
                "username": lg.username,
                "action": lg.action,
                "resourceType": lg.resource_type,
                "resourceId": str(lg.resource_id),
                "detail": {
                    "ip": detail.get("ip", "-"),
                    "ua": detail.get("ua", "-"),
                    "result": detail.get("result", "成功"),
                    "extra": detail.get("extra"),
                },
                "createdAt": lg.created_at.strftime("%Y-%m-%dT%H:%M:%S") if lg.created_at else None,
            }
        )
    return out


# ===================== Notifications =====================


@router.get("/notifications")
def fetch_notifications(
    db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]
):
    # Data scope: all-user notifications (user_id null) + notifications targeted to the current user; never leak others' todos
    items = (
        db.query(Notification)
        .filter(or_(Notification.user_id.is_(None), Notification.user_id == user.id))
        .order_by(Notification.id.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": n.id,
            "type": n.type,
            "title": n.title,
            "content": n.content,
            "read": bool(n.read),
            "createdAt": n.created_at.strftime("%Y-%m-%dT%H:%M:%S") if n.created_at else None,
        }
        for n in items
    ]


@router.post("/notifications/{nid}/read")
def mark_notification_read(
    nid: int, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]
):
    n = db.get(Notification, nid)
    if n and n.user_id is not None and n.user_id != user.id:
        raise AppError("DATA_SCOPE_DENIED", 403, "无权访问该通知")
    if n:
        n.read = True
        db.commit()
    return {"message": "ok"}


# ===================== Model versions =====================


@router.get("/model-versions")
def fetch_model_versions(
    db: Annotated[Session, Depends(get_db)], _: Annotated[User, Depends(require_perm("system:model"))]
):
    items = db.query(ModelVersion).order_by(ModelVersion.id).all()
    out = []
    for m in items:
        metrics = dict(m.eval_metrics or {})
        out.append(
            {
                "id": m.id,
                "modelName": m.model_name,
                "modelType": m.model_type,
                "isDefault": bool(m.is_default),
                "evalMetrics": {
                    "accuracy": metrics.get("accuracy", 0),
                    "falsePositive": metrics.get("falsePositive", 0),
                    "adoptionRate": metrics.get("adoptionRate"),
                },
                "activatedAt": m.activated_at.strftime("%Y-%m-%dT%H:%M:%S") if m.activated_at else None,
            }
        )
    return out


@router.post("/model-versions/{mid}/default")
def set_default_model(
    mid: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    operator: Annotated[User, Depends(require_perm("system:model"))],
):
    ip, ua = _client_info(request)
    m = db.get(ModelVersion, mid)
    if not m:
        raise AppError("MODEL_VERSION_NOT_FOUND", 404, "模型版本不存在")
    if m.is_default:
        raise AppError("MODEL_ALREADY_DEFAULT", 400, "该版本已是当前生效版本")
    for x in db.query(ModelVersion).filter(ModelVersion.model_type == m.model_type).all():
        x.is_default = False
    m.is_default = True
    m.activated_at = datetime.now()
    db.commit()
    write_audit(db, user_id=operator.id, username=operator.username, action="system.model.switch",
                resource_type="模型版本", resource_id=m.model_name, ip=ip, ua=ua,
                extra=f"切换为默认{'审查' if m.model_type == 'llm' else '向量'}模型，新任务生效")
    metrics = dict(m.eval_metrics or {})
    return {
        "id": m.id, "modelName": m.model_name, "modelType": m.model_type, "isDefault": bool(m.is_default),
        "evalMetrics": {
            "accuracy": metrics.get("accuracy", 0),
            "falsePositive": metrics.get("falsePositive", 0),
            "adoptionRate": metrics.get("adoptionRate"),
        },
        "activatedAt": m.activated_at.strftime("%Y-%m-%dT%H:%M:%S") if m.activated_at else None,
    }


# ===================== Runtime model info =====================


@router.get("/runtime-info")
def fetch_runtime_info(_: Annotated[User, Depends(get_current_user)]):
    """Currently active model vendor and model name (for the frontend footer).

    Differs from ``/health``: this endpoint requires login and does NOT probe any external dependency
    (health checks actually connect to MySQL / Redis / ES); suitable for page-load calls.
    """
    from app.ai.providers import ModelConfigError, embedding_endpoint, llm_endpoint
    from app.ai.gateway_models import resolve_alias_map

    # Gateway alias -> real model (display only). Empty dict when the gateway is unavailable; the frontend falls back to showing the alias.
    alias_map: dict[str, dict[str, str]] = {}
    try:
        llm_ep = llm_endpoint()
        alias_map = resolve_alias_map(llm_ep.base_url, llm_ep.api_key)
    except ModelConfigError:
        pass

    def pack(resolver) -> dict:
        try:
            ep = resolver()
        except ModelConfigError as e:  # config errors are still returned so the frontend can show the cause
            return {
                "provider": "-",
                "model": "-",
                "configured": False,
                "dimensions": None,
                "error": str(e),
            }
        info = {
            "provider": ep.provider,
            "model": ep.model,
            "configured": bool(ep.api_key) or not ep.requires_api_key,
            "dimensions": ep.dimensions,
        }
        # Translate the gateway alias (e.g. contract-review) into the real model (e.g. deepseek-v4-flash-vision-exp)
        hit = alias_map.get(ep.model)
        if hit:
            info["realModel"] = hit.get("model")
            info["realProvider"] = hit.get("vendor") or ep.provider
        return info

    return {"llm": pack(llm_endpoint), "embedding": pack(embedding_endpoint)}


# ===================== Prompt templates =====================


@router.get("/prompts")
def fetch_prompts(db: Annotated[Session, Depends(get_db)], _: Annotated[User, Depends(require_perm("system:prompt"))]):
    items = db.query(PromptTemplate).order_by(PromptTemplate.id).all()
    return [
        {
            "id": p.id,
            "version": p.version,
            "scene": p.scene,
            "content": p.content,
            "isActive": bool(p.is_active),
            "updatedAt": p.updated_at.strftime("%Y-%m-%dT%H:%M:%S") if p.updated_at else None,
        }
        for p in items
    ]


@router.put("/prompts/{pid}/content")
def save_prompt_content(
    pid: int,
    payload: SavePromptRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    operator: Annotated[User, Depends(require_perm("system:prompt"))],
):
    ip, ua = _client_info(request)
    p = db.get(PromptTemplate, pid)
    if not p:
        raise AppError("PROMPT_NOT_FOUND", 404, "Prompt 模板不存在")
    if not (payload.content or "").strip():
        raise AppError("PROMPT_CONTENT_EMPTY", 400, "Prompt 内容不能为空")
    p.content = payload.content
    try:  # bump minor version v1.3 -> v1.4
        major, minor = p.version.lstrip("v").split(".")
        p.version = f"v{int(major)}.{int(minor) + 1}"
    except ValueError:
        p.version = p.version + ".1"
    p.updated_at = datetime.now()
    for x in db.query(PromptTemplate).filter(PromptTemplate.scene == p.scene).all():
        x.is_active = False
    p.is_active = True
    db.commit()
    db.refresh(p)
    write_audit(db, user_id=operator.id, username=operator.username, action="system.prompt.publish",
                resource_type="Prompt 模板", resource_id=f"{p.scene} {p.version}", ip=ip, ua=ua,
                extra="发布新版本并激活，新审查任务记录新 prompt_version")
    return {
        "id": p.id, "version": p.version, "scene": p.scene, "content": p.content,
        "isActive": bool(p.is_active),
        "updatedAt": p.updated_at.strftime("%Y-%m-%dT%H:%M:%S") if p.updated_at else None,
    }


@router.post("/prompts/{pid}/activate")
def activate_prompt(
    pid: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    operator: Annotated[User, Depends(require_perm("system:prompt"))],
):
    ip, ua = _client_info(request)
    p = db.get(PromptTemplate, pid)
    if not p:
        raise AppError("PROMPT_NOT_FOUND", 404, "Prompt 模板不存在")
    if p.is_active:
        raise AppError("PROMPT_ALREADY_ACTIVE", 400, "该版本已在激活中")
    for x in db.query(PromptTemplate).filter(PromptTemplate.scene == p.scene).all():
        x.is_active = False
    p.is_active = True
    db.commit()
    db.refresh(p)
    write_audit(db, user_id=operator.id, username=operator.username, action="system.prompt.activate",
                resource_type="Prompt 模板", resource_id=f"{p.scene} {p.version}", ip=ip, ua=ua,
                extra="激活历史 Prompt 版本（同场景互斥）")
    return {
        "id": p.id, "version": p.version, "scene": p.scene, "content": p.content,
        "isActive": bool(p.is_active),
        "updatedAt": p.updated_at.strftime("%Y-%m-%dT%H:%M:%S") if p.updated_at else None,
    }

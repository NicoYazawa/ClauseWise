"""System admin-domain schemas: roles / audit / notifications / model versions / prompts."""
from datetime import datetime

from pydantic import BaseModel, field_serializer

from app.schemas.common import CamelModel, serialize_dt


class RoleInfoOut(CamelModel):
    code: str
    name: str
    description: str = ""
    permissions: list[str] = []
    data_scope: str = "self"


class UpdateRolePermissionsRequest(BaseModel):
    permissions: list[str] = []


class AuditDetailOut(BaseModel):
    ip: str = "-"
    ua: str = "-"
    result: str = "成功"
    extra: str | None = None


class AuditLogOut(BaseModel):
    id: int
    username: str
    action: str
    resource_type: str
    resource_id: str
    detail: AuditDetailOut | None = None
    created_at: str | None = None

    @field_serializer("created_at")
    def _ser(self, v: datetime | None):
        return serialize_dt(v)


class AppNotificationOut(CamelModel):
    id: int
    type: str
    title: str
    content: str
    read: bool = False
    created_at: str | None = None

    @field_serializer("created_at")
    def _ser(self, v: datetime | None):
        return serialize_dt(v)


class EvalMetricsOut(CamelModel):
    accuracy: float = 0.0
    false_positive: float = 0.0
    adoption_rate: float | None = None


class ModelVersionOut(CamelModel):
    id: int
    model_name: str
    model_type: str
    is_default: bool = False
    eval_metrics: EvalMetricsOut | None = None
    activated_at: str | None = None

    @field_serializer("activated_at")
    def _ser(self, v: datetime | None):
        return serialize_dt(v)


class PromptTemplateOut(CamelModel):
    id: int
    version: str
    scene: str
    content: str
    is_active: bool = False
    updated_at: str | None = None

    @field_serializer("updated_at")
    def _ser(self, v: datetime | None):
        return serialize_dt(v)


class SavePromptRequest(BaseModel):
    content: str = ""


class ExportLogRequest(BaseModel):
    format: str = "word"  # word / pdf

"""Auth and user-domain schemas."""
from datetime import datetime

from pydantic import Field, field_serializer

from app.schemas.common import CamelModel


class LoginRequest(CamelModel):
    username: str
    password: str


class ChangePasswordRequest(CamelModel):
    old_password: str = Field(alias="oldPassword", default="")
    new_password: str = Field(alias="newPassword", default="")


class UserOut(CamelModel):
    id: int
    username: str
    real_name: str
    dept_name: str
    title: str
    phone: str = ""
    roles: list[str] = []
    is_active: bool = True
    last_login_at: str | None = None

    @field_serializer("last_login_at")
    def _ser_login(self, v: datetime | str | None):
        from app.schemas.common import serialize_dt

        if v is None:
            return "-"
        if isinstance(v, str):
            return v
        return serialize_dt(v)


class AuthUserOut(UserOut):
    token: str
    role_name: str = ""


class CreateUserRequest(CamelModel):
    username: str
    real_name: str
    dept_name: str = ""
    title: str = ""
    phone: str = ""
    roles: list[str] = []


class UpdateRolesRequest(CamelModel):
    roles: list[str] = []

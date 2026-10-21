"""User & RBAC models: user / role / user_role / permission / role_permission."""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

user_role = Table(
    "user_role",
    Base.metadata,
    Column("user_id", ForeignKey("user.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("role.id", ondelete="CASCADE"), primary_key=True),
)

role_permission = Table(
    "role_permission",
    Base.metadata,
    Column("role_id", ForeignKey("role.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", ForeignKey("permission.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    real_name: Mapped[str] = mapped_column(String(64))
    dept_name: Mapped[str] = mapped_column(String(64), default="未分配")
    title: Mapped[str] = mapped_column(String(64), default="职员")
    phone: Mapped[str | None] = mapped_column(String(255), nullable=True)  # AES-256-GCM encrypted at rest
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    roles: Mapped[list["Role"]] = relationship(secondary=user_role, back_populates="users", lazy="selectin")


class Role(Base):
    __tablename__ = "role"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(255), default="")
    data_scope: Mapped[str] = mapped_column(String(16), default="self")  # self / dept / all

    users: Mapped[list[User]] = relationship(secondary=user_role, back_populates="roles")
    permissions: Mapped[list["Permission"]] = relationship(
        secondary=role_permission, back_populates="roles", lazy="selectin"
    )


class Permission(Base):
    __tablename__ = "permission"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    module: Mapped[str] = mapped_column(String(32), default="")

    roles: Mapped[list[Role]] = relationship(secondary=role_permission, back_populates="permissions")

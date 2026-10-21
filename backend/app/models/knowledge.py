"""Knowledge-base & system models: law_regulation / contract_template / model_version / prompt_template / audit_log / notification."""
from datetime import date, datetime

from sqlalchemy import JSON, BigInteger, Date, DateTime, Integer, String, Text
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LawRegulation(Base):
    __tablename__ = "law_regulation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    doc_type: Mapped[str] = mapped_column(String(16), default="law")  # law / case
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    source_ref: Mapped[str] = mapped_column(String(255), default="")
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active / expired
    vectorized: Mapped[bool] = mapped_column(TINYINT, default=0)
    es_doc_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ContractTemplate(Base):
    __tablename__ = "contract_template"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128))
    contract_type: Mapped[str] = mapped_column(String(32))
    clause_level: Mapped[str] = mapped_column(String(16), default="optional")  # required/recommended/optional
    content: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    es_doc_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vectorized: Mapped[bool] = mapped_column(TINYINT, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class ModelVersion(Base):
    __tablename__ = "model_version"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    model_name: Mapped[str] = mapped_column(String(64))
    model_type: Mapped[str] = mapped_column(String(16))  # llm / embedding
    is_default: Mapped[bool] = mapped_column(TINYINT, default=0)
    eval_metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    activated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class PromptTemplate(Base):
    __tablename__ = "prompt_template"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(32))
    scene: Mapped[str] = mapped_column(String(64), index=True)
    content: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(TINYINT, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class AuditLog(Base):
    """INSERT-ONLY audit log."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    username: Mapped[str] = mapped_column(String(64), default="-")
    action: Mapped[str] = mapped_column(String(32), index=True)
    resource_type: Mapped[str] = mapped_column(String(32), default="")
    resource_id: Mapped[str] = mapped_column(String(128), default="")
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


class Notification(Base):
    __tablename__ = "notification"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)  # null=all users
    type: Mapped[str] = mapped_column(String(32))  # review_done / approval_todo / approval_timeout
    title: Mapped[str] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(Text, default="")
    read: Mapped[bool] = mapped_column(TINYINT, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

"""Approval workflow models: workflow_definition / workflow_instance / approval_record."""
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class WorkflowDefinition(Base):
    __tablename__ = "workflow_definition"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64))
    contract_types: Mapped[list | None] = mapped_column(JSON, nullable=True)
    graph: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {nodes: [...], edges: [...]}
    version: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(TINYINT, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class WorkflowInstance(Base):
    __tablename__ = "workflow_instance"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    definition_id: Mapped[int] = mapped_column(ForeignKey("workflow_definition.id"), index=True)
    definition_name: Mapped[str] = mapped_column(String(64), default="")
    definition_version: Mapped[int] = mapped_column(Integer, default=1)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contract.id", ondelete="CASCADE"), index=True)
    current_node_id: Mapped[str] = mapped_column(String(32), default="start")
    current_node_name: Mapped[str] = mapped_column(String(64), default="发起")
    status: Mapped[str] = mapped_column(String(16), default="running")  # running/approved/rejected/withdrawn
    context_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    node_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # countersign/sequential approval progress {node_id: {"done": [...]}}
    starter_id: Mapped[int] = mapped_column(BigInteger, default=0)
    starter_name: Mapped[str] = mapped_column(String(64), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    records: Mapped[list["ApprovalRecord"]] = relationship(
        back_populates="instance", order_by="ApprovalRecord.id", lazy="selectin"
    )


class ApprovalRecord(Base):
    """Approval trail (append-only, audit basis)."""

    __tablename__ = "approval_record"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    instance_id: Mapped[int] = mapped_column(ForeignKey("workflow_instance.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[str] = mapped_column(String(32))
    node_name: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(16))  # submit/approve/reject/return/transfer/countersign/withdraw/urge
    operator_id: Mapped[int] = mapped_column(BigInteger, default=0)
    operator_name: Mapped[str] = mapped_column(String(64), default="")
    comment: Mapped[str] = mapped_column(String(1024), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    instance = relationship("WorkflowInstance", back_populates="records")

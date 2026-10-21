"""AI review domain models: review_task / risk_finding / review_report."""
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ReviewTask(Base):
    __tablename__ = "review_task"
    # task_key is a plain index: idempotency only blocks "in-progress" duplicate submissions (pending/running),
    # failures/completions are allowed to re-submit the same key (a table-wide unique would block re-reviews)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contract.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    task_type: Mapped[str] = mapped_column(String(16))  # full / clause / diff
    clause_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    base_version_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/running/completed/failed
    progress: Mapped[int] = mapped_column(Integer, default=0)
    model_version: Mapped[str] = mapped_column(String(64), default="")
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    task_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    error_msg: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)

    contract = relationship("Contract", lazy="joined")
    findings: Mapped[list["RiskFinding"]] = relationship(back_populates="task", lazy="selectin")
    report: Mapped["ReviewReport | None"] = relationship(back_populates="task", uselist=False, lazy="selectin")


class RiskFinding(Base):
    __tablename__ = "risk_finding"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("review_task.id", ondelete="CASCADE"), index=True)
    clause_id: Mapped[int] = mapped_column(BigInteger, default=0)
    clause_no: Mapped[str] = mapped_column(String(64), default="")
    risk_level: Mapped[str] = mapped_column(String(8))  # high / medium / low
    risk_type: Mapped[str] = mapped_column(String(32))
    issue: Mapped[str] = mapped_column(Text)
    original_text: Mapped[str] = mapped_column(Text, default="")
    legal_basis: Mapped[str] = mapped_column(String(1024), default="")
    suggestion: Mapped[str] = mapped_column(Text, default="")
    suggested_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    rag_hits: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(8))  # rule / llm
    status: Mapped[str] = mapped_column(String(16), default="open")  # open/accepted/rejected/fixed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    task = relationship("ReviewTask", back_populates="findings")


class ReviewReport(Base):
    __tablename__ = "review_report"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("review_task.id", ondelete="CASCADE"), unique=True)
    contract_id: Mapped[int] = mapped_column(BigInteger, index=True)
    # Review-object binding: a report is only responsible for the version and content hash at its generation time; absent = historical report (requires re-review)
    version_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    high_count: Mapped[int] = mapped_column(Integer, default=0)
    medium_count: Mapped[int] = mapped_column(Integer, default=0)
    low_count: Mapped[int] = mapped_column(Integer, default=0)
    overall_opinion: Mapped[str] = mapped_column(Text, default="")
    report_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    es_doc_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    task = relationship("ReviewTask", back_populates="report")

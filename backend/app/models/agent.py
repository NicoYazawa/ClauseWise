"""Multi-agent collaboration trace models: agent_trace (registered agents' step-by-step execution persisted for the frontend timeline)."""
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class QaSession(Base):
    __tablename__ = "qa_session"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class AgentTrace(Base):
    __tablename__ = "agent_trace"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_type: Mapped[str] = mapped_column(String(16), index=True)  # review / qa
    ref_id: Mapped[int] = mapped_column(BigInteger, default=0, index=True)  # review task id / QA session id
    agent_name: Mapped[str] = mapped_column(String(64))  # agent name within the registry
    role: Mapped[str] = mapped_column(String(32))  # agent role display name (Planner / Clause Reviewer ...)
    step_idx: Mapped[int] = mapped_column(Integer, default=0)  # timeline index
    action: Mapped[str] = mapped_column(String(32))  # plan / tool_call / decision / message / report ...
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # input summary / output / tool call details
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

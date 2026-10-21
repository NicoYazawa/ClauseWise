"""Contract domain models: contract / contract_version / contract_clause."""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Contract(Base):
    __tablename__ = "contract"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    contract_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    contract_type: Mapped[str] = mapped_column(String(32))  # purchase/sales/labor/lease/nda/other
    owner_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # 3.3.3 state machine, 11 states
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    file_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Counterparty info (id_no / phone AES-256-GCM encrypted)
    counterparty_name: Mapped[str] = mapped_column(String(255), default="")
    counterparty_id_no_enc: Mapped[str | None] = mapped_column(String(512), nullable=True)
    counterparty_phone_enc: Mapped[str | None] = mapped_column(String(512), nullable=True)
    amount: Mapped[int] = mapped_column(BigInteger, default=0)  # yuan
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    owner = relationship("User", lazy="joined")
    versions: Mapped[list["ContractVersion"]] = relationship(
        back_populates="contract", order_by="ContractVersion.version_no", lazy="selectin"
    )


class ContractVersion(Base):
    __tablename__ = "contract_version"
    __table_args__ = (UniqueConstraint("contract_id", "version_no", name="uq_version"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contract.id", ondelete="CASCADE"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    parent_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # version tree
    file_name: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)  # relative path
    file_size_kb: Mapped[int] = mapped_column(Integer, default=0)
    parse_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/parsing/parsed/failed
    parse_channel: Mapped[str | None] = mapped_column(String(16), nullable=True)  # text/vision/mixed
    parse_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    contract = relationship("Contract", back_populates="versions")
    clauses: Mapped[list["ContractClause"]] = relationship(
        back_populates="version", order_by="ContractClause.id", lazy="selectin"
    )


class ContractClause(Base):
    __tablename__ = "contract_clause"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("contract_version.id", ondelete="CASCADE"), index=True)
    contract_id: Mapped[int] = mapped_column(BigInteger, index=True)
    clause_no: Mapped[str] = mapped_column(String(64))
    clause_type: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    page_no: Mapped[int] = mapped_column(Integer, default=1)
    char_start: Mapped[int] = mapped_column(Integer, default=0)
    char_end: Mapped[int] = mapped_column(Integer, default=0)

    version = relationship("ContractVersion", back_populates="clauses")

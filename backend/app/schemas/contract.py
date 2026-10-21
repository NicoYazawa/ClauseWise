"""Contract-domain schemas."""
from datetime import datetime

from pydantic import Field, field_serializer

from app.schemas.common import CamelModel, serialize_dt


class CounterpartyOut(CamelModel):
    name: str = ""
    id_no: str = Field(default="", alias="idNo")
    phone: str = ""


class ContractOut(CamelModel):
    id: int
    contract_no: str
    title: str
    contract_type: str
    owner_id: int
    owner_name: str = ""
    status: str
    current_version: int
    counterparty: CounterpartyOut = CounterpartyOut()
    amount: int = 0
    created_at: str | None = None
    updated_at: str | None = None

    @field_serializer("created_at", "updated_at")
    def _ser(self, v: datetime | None):
        return serialize_dt(v)


class VersionOut(CamelModel):
    id: int
    contract_id: int
    version_no: int
    parent_id: int | None = None
    file_name: str
    file_size_kb: int = 0
    parse_status: str
    parse_channel: str | None = None
    created_at: str | None = None

    @field_serializer("created_at")
    def _ser(self, v: datetime | None):
        return serialize_dt(v)


class ClauseOut(CamelModel):
    id: int
    version_id: int
    contract_id: int
    clause_no: str
    clause_type: str
    content: str
    page_no: int = 1


class ClauseDiffItemOut(CamelModel):
    clause_no: str
    kind: str  # added / removed / modified / drift
    old_text: str = ""
    new_text: str = ""
    summary: str = ""


class UploadContractRequest(CamelModel):
    """multipart form fields."""

    title: str
    contract_type: str
    counterparty_name: str = ""
    amount: int = 0

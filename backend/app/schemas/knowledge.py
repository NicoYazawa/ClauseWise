"""Knowledge-base domain schemas."""
from datetime import date

from pydantic import field_serializer

from app.schemas.common import CamelModel, serialize_date


class LawRegulationOut(CamelModel):
    id: int
    doc_type: str
    title: str
    content: str
    source_ref: str = ""
    effective_date: str | None = None
    expiry_date: str | None = None
    status: str = "active"
    vectorized: bool = False
    hit_count: int = 0

    @field_serializer("effective_date", "expiry_date")
    def _ser(self, v: date | None):
        return serialize_date(v)


class SaveLawRequest(CamelModel):
    id: int | None = None
    doc_type: str = "law"
    title: str
    content: str
    source_ref: str = ""
    effective_date: str | None = None
    expiry_date: str | None = None
    status: str = "active"


class ContractTemplateOut(CamelModel):
    id: int
    name: str
    contract_type: str
    clause_level: str
    content: str
    version: int = 1


class SaveTemplateRequest(CamelModel):
    id: int | None = None
    name: str
    contract_type: str
    clause_level: str = "optional"
    content: str


class ImportResultOut(CamelModel):
    imported: int = 0
    vectorized: int = 0

"""AI review-domain schemas."""
from datetime import datetime

from pydantic import field_serializer

from app.schemas.common import CamelModel, serialize_dt


class ReviewTaskOut(CamelModel):
    id: int
    contract_id: int
    contract_title: str = ""
    task_type: str
    clause_no: str | None = None
    status: str
    progress: int = 0
    model_version: str = ""
    prompt_version: str = ""
    error_msg: str | None = None
    created_at: str | None = None
    completed_at: str | None = None
    duration_ms: int | None = None

    @field_serializer("created_at", "completed_at")
    def _ser(self, v: datetime | None):
        return serialize_dt(v)


class StartReviewRequest(CamelModel):
    contract_id: int
    task_type: str = "full"
    base_version_no: int | None = None
    clause_no: str | None = None


class ResolveFindingRequest(CamelModel):
    status: str  # accepted / rejected / fixed / open


class RiskFindingOut(CamelModel):
    id: int
    task_id: int
    clause_no: str = ""
    clause_id: int = 0
    risk_level: str
    risk_type: str
    issue: str
    original_text: str = ""
    legal_basis: str = ""
    suggestion: str = ""
    suggested_text: str | None = None
    rag_hits: list[str] | None = None
    source: str
    status: str = "open"


class ReportSummaryOut(CamelModel):
    high: int = 0
    medium: int = 0
    low: int = 0
    score: int = 0
    """Rule-engine blocking items (scoring and approval thresholds only look at these; high/medium/low are the full stats including AI references)."""
    blockingHigh: int = 0
    aiHigh: int = 0
    aiMedium: int = 0
    aiLow: int = 0


class ReportMetaOut(CamelModel):
    model: str = ""
    prompt_version: str = ""
    tokens_used: int = 0
    duration_ms: int = 0


class ReviewReportOut(CamelModel):
    id: int
    task_id: int
    contract_id: int
    summary: ReportSummaryOut = ReportSummaryOut()
    overall_opinion: str = ""
    findings: list[RiskFindingOut] = []
    meta: ReportMetaOut = ReportMetaOut()
    created_at: str | None = None

    @field_serializer("created_at")
    def _ser(self, v: datetime | None):
        return serialize_dt(v)


class ProgressOut(CamelModel):
    task_id: int
    status: str
    progress: int
    error_msg: str | None = None

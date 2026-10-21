"""Smart-QA domain schemas."""
from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str
    sessionId: int | None = Field(default=None, gt=0)


class QaCitationOut(BaseModel):
    kind: str  # law / case / template
    id: int
    title: str
    snippet: str
    score: float


class AskResultOut(BaseModel):
    answer: str
    sessionId: int
    citations: list[QaCitationOut] = []

"""Intelligent Q&A endpoints: RAG retrieval + DeepSeek generation (real calls, SSE streaming)."""
import json
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy.orm import Session

from app.ai import llm_client
from app.core.exceptions import AppError
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.qa import AskRequest
from app.services import qa_service

router = APIRouter(prefix="/qa", tags=["Intelligent QA"])


@router.post("/ask")
def ask(
    payload: AskRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    if not payload.question.strip():
        raise AppError("QA_EMPTY_QUESTION", 400, "问题不能为空")
    session = qa_service.get_session(db, user, payload.sessionId)
    return qa_service.ask(db, payload.question, session_id=session.id)


def _sse(payload: dict) -> str:
    """Encode an SSE event frame (data line + blank-line separator; UTF-8 Chinese not escaped)."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/ask/stream")
def ask_stream(
    payload: AskRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Streaming Q&A (SSE): event sequence citations -> delta* -> done / error.

    Validation errors (empty question / unconfigured keys) are raised before the stream opens (standard 4xx/5xx JSON);
    exceptions during generation are emitted as error events, so the frontend stays aware instead of a silent stream break.
    """
    question = (payload.question or "").strip()
    if not question:
        raise AppError("QA_EMPTY_QUESTION", 400, "问题不能为空")
    llm_client.ensure_llm_configured()
    session = qa_service.get_session(db, user, payload.sessionId)

    def event_source():
        try:
            yield _sse({"type": "session", "sessionId": session.id})
            for evt in qa_service.ask_stream(db, question, session_id=session.id):
                yield _sse(evt)
        except Exception as e:  # noqa: BLE001
            logger.error(f"QA stream failed: {e}")
            yield _sse({"type": "error", "detail": "模型生成失败，请稍后重试"})

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            # Explicitly declare identity: Starlette GZipMiddleware passes through responses already carrying Content-Encoding,
            # avoiding zlib compression buffering that would break per-chunk real-time delivery
            "Content-Encoding": "identity",
        },
    )

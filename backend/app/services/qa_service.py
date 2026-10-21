"""Intelligent Q&A service (Agentic RAG multi-agent pipeline, orchestrated by LangGraph):

- Pipeline: intent routing -> query planning -> hybrid retrieval -> quality assessment -> (CRAG corrective re-retrieval, <=1 round)
  -> citation generation (streaming) -> SelfRAG reflection (regenerate with feedback if not passing, <=1 time)
- ask returns {answer, citations, sessionId}; the API stream announces its owned session first;
  added agent_step (agent decision chain) and reset (clear current answer on reflection regeneration); old frontend ignoring new events still works
- Matched entry hit_count + 1 (knowledge quality reverse-evaluation, 3.4.1)
"""
from app.ai import llm_client
from app.core.exceptions import AppError
from app.models.agent import QaSession
from app.models.knowledge import LawRegulation


def get_session(db, user, session_id: int | None = None) -> QaSession:
    """Resolve only owned sessions, or allocate a fresh server-generated session."""
    if session_id is not None:
        session = db.query(QaSession).filter(QaSession.id == session_id, QaSession.user_id == user.id).first()
        if session is None:
            raise AppError("QA_SESSION_NOT_FOUND", 404, "问答会话不存在")
        return session
    session = QaSession(user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def ask(db, question: str, *, session_id: int = 0) -> dict:
    question = (question or "").strip()
    if not question:
        raise AppError("QA_EMPTY_QUESTION", 400, "问题不能为空")
    llm_client.ensure_llm_configured()

    from app.agents.qa_graph import run_qa_graph

    result = run_qa_graph(question, session_id=session_id)
    _bump_hit_counts(db, result.get("relevant_hits") or [])
    return {"answer": result["answer"], "citations": result["citations"], "sessionId": session_id}


def ask_stream(db, question: str, *, session_id: int = 0):
    """SSE streaming Q&A event generator: agent_step* -> citations -> delta* (-> reset -> delta*) -> done.

    Citations and decision chains are pushed first so the frontend can show sources and the agent collaboration
    during generation; hit stats are applied after the stream ends.
    """
    from app.agents.qa_graph import stream_qa_graph

    relevant: list[dict] = []
    for evt in stream_qa_graph(question, session_id=session_id):
        if evt["type"] == "_hits":  # internal event: final relevant hits for stats, not sent to the frontend
            relevant = evt["hits"]
            continue
        yield evt
    _bump_hit_counts(db, relevant)


def _bump_hit_counts(db, hits: list[dict]) -> None:
    """Knowledge hit stats: bump law/case hits by 1 (failure doesn't affect answer output)."""
    try:
        for h in hits:
            if h.get("kind") in ("law", "case") and h.get("ref_id"):
                law = db.get(LawRegulation, int(h["ref_id"]))
                if law:
                    law.hit_count = (law.hit_count or 0) + 1
        db.commit()
    except Exception:
        db.rollback()

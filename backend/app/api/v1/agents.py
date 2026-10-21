"""Multi-Agent observability endpoints: registry listing + collaboration trace timeline (agent_trace).

Graph modules (review_graph / qa_graph) trigger registration via lazy imports inside their functions:
when LangGraph isn't installed the service still boots; only this endpoint and the agent chains are unavailable.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.access import visible_contract_ids
from app.core.exceptions import AppError
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.agent import AgentTrace, QaSession
from app.models.review import ReviewTask
from app.models.user import User

router = APIRouter(prefix="/agents", tags=["Multi-Agent"])


def _trace_out(t: AgentTrace) -> dict:
    return {
        "id": t.id,
        "taskType": t.task_type,
        "refId": t.ref_id,
        "sessionId": t.ref_id if t.task_type == "qa" else None,
        "agentName": t.agent_name,
        "role": t.role,
        "stepIdx": t.step_idx,
        "action": t.action,
        "payload": t.payload or {},
        "tokens": t.tokens,
        "latencyMs": t.latency_ms,
        "error": t.error,
        "createdAt": t.created_at.strftime("%Y-%m-%dT%H:%M:%S") if t.created_at else None,
    }


def _visible_traces(user):
    sessions = select(QaSession.id).where(QaSession.user_id == user.id)
    tasks = select(ReviewTask.id).where(ReviewTask.contract_id.in_(visible_contract_ids(user)))
    return or_(
        and_(AgentTrace.task_type == "qa", AgentTrace.ref_id > 0, AgentTrace.ref_id.in_(sessions)),
        and_(AgentTrace.task_type == "review", AgentTrace.ref_id.in_(tasks)),
    )


@router.get("")
def list_agents(_: Annotated[User, Depends(get_current_user)]):
    """Agent registry: role listings from each collaboration graph (name/role/duty/tools/owning graph)."""
    from app.agents import qa_graph, review_graph  # noqa: F401  import triggers registration
    from app.agents.registry import list_agents as _list

    return [
        {
            "name": s.name,
            "role": s.role,
            "description": s.description,
            "descKey": s.desc_key,
            "graph": s.graph,
            "kind": s.kind,
            "tools": s.tools,
        }
        for s in _list()
    ]


@router.get("/trace")
def get_trace(
    task_type: Annotated[str, Query(description="review / qa")],
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    ref_id: Annotated[int | None, Query(description="review task id / QA session id；缺省按 0（历史留痕）")] = None,
):
    """Multi-agent collaboration timeline for one task (in step order)."""
    if task_type not in ("review", "qa"):
        raise AppError("AGENT_INVALID_TASK_TYPE", 400, "task_type 仅支持 review / qa")
    target_ref = 0 if ref_id is None else ref_id
    rows = (
        db.query(AgentTrace)
        .filter(AgentTrace.task_type == task_type, AgentTrace.ref_id == target_ref, _visible_traces(user))
        .order_by(AgentTrace.id.asc())
        .limit(500)
        .all()
    )
    if not rows:
        # Traces exist but are not visible: reject explicitly instead of silently returning an empty list that would mask unauthorized access
        exists = (
            db.query(AgentTrace.id)
            .filter(AgentTrace.task_type == task_type, AgentTrace.ref_id == target_ref)
            .first()
        )
        if exists:
            raise AppError("DATA_SCOPE_DENIED", 403, "无权访问该任务的 Agent 留痕")
    return [_trace_out(t) for t in rows]


@router.get("/trace/recent")
def recent_traces(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=200)] = 60,
):
    """Recent collaboration traces (data source for the Agent overview page): newest N steps across all types."""
    rows = (
        db.query(AgentTrace)
        .filter(_visible_traces(user))
        .order_by(AgentTrace.id.desc())
        .limit(limit)
        .all()
    )
    return [_trace_out(t) for t in reversed(rows)]

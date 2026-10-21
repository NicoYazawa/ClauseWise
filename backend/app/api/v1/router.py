"""API v1 router aggregation."""
from fastapi import APIRouter

from app.api.v1 import agents, alerts, auth, contracts, knowledge, qa, reviews, system, workflows

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(alerts.router)
api_router.include_router(contracts.router)
api_router.include_router(reviews.router)
api_router.include_router(workflows.router)
api_router.include_router(knowledge.router)
api_router.include_router(qa.router)
api_router.include_router(system.router)
api_router.include_router(agents.router)


# ===== Supplement: all risk findings (data source for the workbench risk-distribution chart) =====
from typing import Annotated  # noqa: E402

from fastapi import APIRouter, Depends  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.security import get_current_user
from app.core.access import visible_contract_ids  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.models.review import RiskFinding, ReviewTask  # noqa: E402
from app.models.user import User  # noqa: E402

findings_router = APIRouter()


@findings_router.get("/findings")
def fetch_all_findings(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    items = db.query(RiskFinding).join(ReviewTask, RiskFinding.task_id == ReviewTask.id).filter(ReviewTask.contract_id.in_(visible_contract_ids(user))).order_by(RiskFinding.id.desc()).limit(500).all()
    return [
        {
            "id": f.id,
            "taskId": f.task_id,
            "clauseNo": f.clause_no,
            "clauseId": f.clause_id,
            "riskLevel": f.risk_level,
            "riskType": f.risk_type,
            "issue": f.issue,
            "originalText": f.original_text,
            "legalBasis": f.legal_basis,
            "suggestion": f.suggestion,
            "suggestedText": f.suggested_text,
            "ragHits": f.rag_hits or [],
            "source": f.source,
            "status": f.status,
        }
        for f in items
    ]


api_router.include_router(findings_router)

"""AI review endpoints (design doc 3.2): task list/detail/progress polling/report/start/review/risk disposition/export."""
import re
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from app.core.exceptions import AppError
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.access import get_contract_for_user, visible_contract_ids
from app.core.request_ctx import client_info as _client_info
from app.core.security import ensure_perm, get_current_user, require_perm
from app.db.session import get_db
from app.models.contract import Contract, ContractClause, ContractVersion
from app.models.review import ReviewReport, ReviewTask, RiskFinding
from app.models.user import User
from app.schemas.review import ResolveFindingRequest, StartReviewRequest
from app.services import contract_service
from app.tasks.dispatcher import submit_review_task

router = APIRouter(tags=["AI Review"])


def _task_out(t: ReviewTask) -> dict:
    return {
        "id": t.id,
        "contractId": t.contract_id,
        "contractTitle": t.contract.title if t.contract else "",
        "taskType": t.task_type,
        "clauseNo": t.clause_no,
        "status": t.status,
        "progress": t.progress,
        "modelVersion": t.model_version,
        "promptVersion": t.prompt_version,
        "errorMsg": t.error_msg,
        "createdAt": t.created_at.strftime("%Y-%m-%dT%H:%M:%S") if t.created_at else None,
        "completedAt": t.completed_at.strftime("%Y-%m-%dT%H:%M:%S") if t.completed_at else None,
        "durationMs": t.duration_ms,
    }


def _finding_out(f: RiskFinding) -> dict:
    return {
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


def _report_out(r: ReviewReport, findings: list[RiskFinding], t: ReviewTask) -> dict:
    # summary: high/medium/low are full stats including AI suggestions; score/blockingHigh follow the rule engine (scoring & approval threshold)
    js = (r.report_json or {}).get("summary", {}) if r.report_json else {}
    return {
        "id": r.id,
        "taskId": r.task_id,
        "contractId": r.contract_id,
        "summary": {
            "high": js.get("high", r.high_count),
            "medium": js.get("medium", r.medium_count),
            "low": js.get("low", r.low_count),
            "score": r.score,
            "blockingHigh": js.get("blockingHigh", r.high_count),
            "aiHigh": js.get("aiHigh", 0),
            "aiMedium": js.get("aiMedium", 0),
            "aiLow": js.get("aiLow", 0),
            # nonzero means some clauses were skipped (incomplete-report flag); 0 means all clauses were reviewed
            "failedClauses": js.get("failedClauses", 0),
            # true = content/version changed or the historical report is not content-bound; re-review is required before it can be used for approval
            "needsReReview": js.get("needsReReview", False),
            "taskType": js.get("taskType", t.task_type),
        },
        "overallOpinion": r.overall_opinion,
        "findings": [_finding_out(f) for f in findings],
        "meta": {
            "model": t.model_version,
            "promptVersion": t.prompt_version,
            "tokensUsed": t.tokens_used or 0,
            "durationMs": t.duration_ms or 0,
        },
        "createdAt": r.created_at.strftime("%Y-%m-%dT%H:%M:%S") if r.created_at else None,
    }


def _get_task_or_404(db: Session, task_id: int, user: User) -> ReviewTask:
    t = db.get(ReviewTask, task_id)
    if not t:
        raise AppError("REVIEW_TASK_NOT_FOUND", 404, "任务不存在")
    get_contract_for_user(db, user, t.contract_id)
    return t


@router.get("/review-tasks")
def fetch_tasks(db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    tasks = db.query(ReviewTask).filter(ReviewTask.contract_id.in_(visible_contract_ids(user))).order_by(ReviewTask.id.desc()).all()
    return [_task_out(t) for t in tasks]


@router.get("/review-tasks/{task_id}")
def fetch_task(
    task_id: int, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]
):
    return _task_out(_get_task_or_404(db, task_id, user))


@router.get("/review-tasks/{task_id}/progress")
def fetch_task_progress(
    task_id: int, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]
):
    t = _get_task_or_404(db, task_id, user)
    return {"taskId": t.id, "status": t.status, "progress": t.progress, "errorMsg": t.error_msg}


@router.get("/review-tasks/{task_id}/report")
def fetch_report(
    task_id: int, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]
):
    t = _get_task_or_404(db, task_id, user)
    report = db.query(ReviewReport).filter(ReviewReport.task_id == task_id).first()
    if not report:
        return None
    findings = db.query(RiskFinding).filter(RiskFinding.task_id == task_id).order_by(RiskFinding.id).all()
    return _report_out(report, findings, t)


@router.post("/review-tasks")
def start_review(
    payload: StartReviewRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    operator: Annotated[User, Depends(require_perm("review:rerun"))],
):
    ip, ua = _client_info(request)
    contract = get_contract_for_user(db, operator, payload.contract_id)
    latest = (
        db.query(ContractVersion)
        .filter(
            ContractVersion.contract_id == contract.id,
            ContractVersion.version_no == contract.current_version,
        )
        .first()
    )
    if not latest or latest.parse_status != "parsed":
        raise AppError("REVIEW_NOT_PARSED", 400, "该合同尚未完成解析，无法发起审查")
    if payload.task_type not in ("full", "clause", "diff"):
        raise AppError("REVIEW_INVALID_TYPE", 400, "非法任务类型")
    if payload.task_type == "clause" and not payload.clause_no:
        raise AppError("REVIEW_CLAUSE_REQUIRED", 400, "单条款审查需选择目标条款")
    if payload.task_type == "diff" and not payload.base_version_no:
        payload.base_version_no = max(1, contract.current_version - 1)

    # Idempotency: an in-progress task of the same version+type is returned directly (task_key unique constraint);
    # zombie tasks (stuck pending/running due to restart / no Worker) are reclaimed first, allowing a re-submit
    from datetime import datetime

    from app.services.review_service import recover_task, stale_reason

    task_key = f"{latest.id}:{payload.task_type}:{payload.clause_no or '-'}"
    existing = (
        db.query(ReviewTask)
        .filter(ReviewTask.task_key == task_key, ReviewTask.status.in_(("pending", "running")))  # type: ignore[arg-type]
        .first()
    )
    if existing:
        reason = stale_reason(existing, datetime.now())
        if reason:
            recover_task(db, existing, reason)
        else:
            return _task_out(existing)

    task = ReviewTask(
        contract_id=contract.id,
        version_id=latest.id,
        task_type=payload.task_type,
        clause_no=payload.clause_no,
        base_version_no=payload.base_version_no,
        status="pending",
        progress=0,
        model_version="",  # filled back on task completion
        prompt_version="",
        task_key=task_key,
        created_at=datetime.now(),
    )
    db.add(task)
    # A partial (single-clause / incremental) review does not mean the whole contract is under review; it does not change the overall status
    if payload.task_type == "full":
        contract.status = "under_review"
        contract.updated_at = datetime.now()
    db.commit()
    db.refresh(task)
    write_audit(db, user_id=operator.id, username=operator.username, action="review.start",
                resource_type="审查任务", resource_id=str(task.id), ip=ip, ua=ua,
                extra=f"任务类型 {payload.task_type}，条款 {payload.clause_no or '-'}")
    submit_review_task(task.id)
    return _task_out(task)


@router.put("/findings/{finding_id}/status")
def resolve_finding(
    finding_id: int,
    payload: ResolveFindingRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    operator: Annotated[User, Depends(require_perm("review:resolve"))],
):
    """Risk disposition: accepting with full suggested text amends the clause into a NEW version
    (old versions and their reports stay immutable and lose approval eligibility);
    without suggested text (e.g. missing-clause) the finding is only marked accepted."""
    ip, ua = _client_info(request)
    if payload.status not in ("open", "accepted", "rejected", "fixed"):
        raise AppError("REVIEW_INVALID_FINDING_STATUS", 400, "非法处置状态")
    f = db.get(RiskFinding, finding_id)
    if not f:
        raise AppError("REVIEW_FINDING_NOT_FOUND", 404, "风险项不存在")
    _get_task_or_404(db, f.task_id, operator)
    applied = False
    clause = db.get(ContractClause, f.clause_id) if (payload.status == "accepted" and f.clause_id) else None
    if clause and (f.suggested_text or "").strip():
        new_text = f.suggested_text.strip()
        # When suggested text lacks the clause number, keep the original "第X条 Title：" prefix to preserve clause-splitting location
        m = re.match(r"(第[零一二三四五六七八九十百千\d]+条\s*[^：]*：)", clause.content)
        if m and not new_text.startswith(clause.clause_no):
            new_text = m.group(1) + new_text
        if new_text != clause.content:
            # An amendment creates a new version (the old version/report is immutable and loses approval eligibility)
            # instead of mutating the reviewed clause in place
            # Authorize against contract:upload: adopting a suggestion is contract write capability (new version +
            # materialized amended DOCX), so review:resolve alone must not be able to rewrite the contract body.
            # Checked before writing anything, so a denial leaves no pending state behind.
            ensure_perm(operator, "contract:upload",
                        "采纳建议会生成合同新版本并重写条款正文，需具备合同上传/修订权限")
            contract_service.amend_clause(db, clause, new_text)
        applied = True
        f.status = "fixed"  # suggestion already applied via the new version
    else:
        f.status = payload.status
    db.commit()
    db.refresh(f)
    action_map = {"accepted": "finding.accept", "rejected": "finding.reject", "fixed": "finding.fix"}
    if payload.status in action_map:
        write_audit(db, user_id=operator.id, username=operator.username, action=action_map[payload.status],
                    resource_type="风险发现", resource_id=str(f.id), ip=ip, ua=ua,
                    extra=f"{f.clause_no} {f.risk_type} → {f.status}"
                    + ("，条款内容已按建议自动修订" if applied else ""))
    return {**_finding_out(f), "applied": applied}


@router.post("/review-tasks/{task_id}/export")
def log_report_export(
    task_id: int,
    payload: dict,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    operator: Annotated[User, Depends(require_perm("review:export"))],
):
    """Export audit trail (3.5.4: retain >= 3 years)."""
    ip, ua = _client_info(request)
    t = _get_task_or_404(db, task_id, operator)
    fmt = (payload or {}).get("format", "word")
    write_audit(db, user_id=operator.id, username=operator.username, action="review.export",
                resource_type="审查报告", resource_id=str(task_id), ip=ip, ua=ua,
                extra=f"导出 {'Word' if fmt == 'word' else 'PDF'} 格式报告（合同：{t.contract.title if t.contract else task_id}）")
    return {"message": "导出留痕已记录"}


@router.get("/review-tasks/{task_id}/export")
def export_report(
    task_id: int,
    request: Request,
    format: str = "word",
    db: Annotated[Session, Depends(get_db)] = None,
    user: Annotated[User, Depends(require_perm("review:export"))] = None,
):
    """Real file export: Word (python-docx) / PDF (reportlab)."""
    t = _get_task_or_404(db, task_id, user)
    report = db.query(ReviewReport).filter(ReviewReport.task_id == task_id).first()
    if not report:
        raise AppError("REVIEW_REPORT_NOT_GENERATED", 404, "报告尚未生成")
    findings = db.query(RiskFinding).filter(RiskFinding.task_id == task_id).order_by(RiskFinding.id).all()
    from app.services import report_export

    if format == "pdf":
        content = report_export.export_pdf(report, t, findings)
        media_type = "application/pdf"
        fname = f"审查报告_任务{task_id}.pdf"
    else:
        content = report_export.export_word(report, t, findings)
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        fname = f"审查报告_任务{task_id}.docx"
    # Chinese filenames need RFC 5987 percent-encoding: HTTP headers only support latin-1, so embedding raw Chinese causes a 500
    ip, ua = _client_info(request)
    write_audit(db, user_id=user.id, username=user.username, action="review.export",
                resource_type="审查报告", resource_id=str(task_id), ip=ip, ua=ua, extra=f"导出 {format}")
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}"},
    )

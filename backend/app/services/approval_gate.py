"""Approval eligibility gate — the single authority for "may this contract enter approval".

Design rule (audit fix): eligibility is computed independently from the report's immutable
bindings, never from `contract.status == review_passed` alone:

1. current version   — the qualifying report must belong to the contract's current version
2. full review       — only task_type == "full" qualifies (clause/diff are partial views)
3. zero missed       — failedClauses == 0 (no clause was skipped/degraded away)
4. score threshold   — rule-engine score >= 85
5. no blocking item  — rule-engine high_count == 0
6. content binding   — report.content_hash must match the current clause content (amended
                       content invalidates the old report), and legacy unbound reports
                       (no hash) are treated as "needs re-review", never auto-approved
"""
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.contract import Contract, ContractVersion
from app.models.review import ReviewReport, ReviewTask
from app.services.review_service import version_content_hash

SCORE_THRESHOLD = 85


@dataclass
class Reason:
    code: str
    message: str


@dataclass
class ApprovalEligibility:
    eligible: bool
    reasons: list[Reason] = field(default_factory=list)
    report: ReviewReport | None = None
    task: ReviewTask | None = None

    def raise_for_status(self) -> None:
        if not self.eligible:
            from app.core.exceptions import AppError

            first = self.reasons[0]
            raise AppError(first.code, 400, "；".join(r.message for r in self.reasons))


def evaluate(db: Session, contract: Contract) -> ApprovalEligibility:
    """Compute approval eligibility for a contract from its current version's report bindings."""
    version = (
        db.query(ContractVersion)
        .filter(
            ContractVersion.contract_id == contract.id,
            ContractVersion.version_no == contract.current_version,
        )
        .first()
    )
    if not version:
        return ApprovalEligibility(False, [Reason("WORKFLOW_NO_REVIEW_REPORT", "合同当前版本不存在，无法发起审批")])

    task = (
        db.query(ReviewTask)
        .filter(
            ReviewTask.contract_id == contract.id,
            ReviewTask.version_id == version.id,
            ReviewTask.task_type == "full",
            ReviewTask.status == "completed",
        )
        .order_by(ReviewTask.id.desc())
        .first()
    )
    report = db.query(ReviewReport).filter(ReviewReport.task_id == task.id).first() if task else None
    if not task or not report:
        return ApprovalEligibility(
            False, [Reason("WORKFLOW_NO_REVIEW_REPORT", "该合同当前版本没有已完成的全文审查报告，无法发起审批")]
        )

    reasons: list[Reason] = []
    summary = ((report.report_json or {}).get("summary") or {}) if report.report_json else {}
    if summary.get("needsReReview"):
        reasons.append(
            Reason("WORKFLOW_REPORT_STALE", "该报告已标记为需重新审查（审查对象已变更或属历史报告），请重新审查后再发起审批")
        )
    if report.version_id is None or report.content_hash is None:
        reasons.append(
            Reason("WORKFLOW_REPORT_STALE", "该报告缺少版本/内容绑定（历史报告），无法确认对应合同内容，需重新审查")
        )
    else:
        if report.version_id != version.id:
            reasons.append(Reason("WORKFLOW_REPORT_STALE", "报告对应的不是合同当前版本，请重新审查"))
        if report.content_hash != version_content_hash(db, version.id):
            reasons.append(Reason("WORKFLOW_REPORT_STALE", "报告生成后合同内容已发生修订，原报告失效，请重新审查"))
    if summary.get("failedClauses", 0) > 0:
        reasons.append(
            Reason("WORKFLOW_REPORT_INCOMPLETE", f"审查不完整：{summary.get('failedClauses')} 条条款审查失败/漏审，请重新审查")
        )
    if report.high_count > 0:
        reasons.append(Reason("WORKFLOW_THRESHOLD_NOT_MET", f"存在 {report.high_count} 项高风险阻断项，不能发起审批"))
    if report.score < SCORE_THRESHOLD:
        reasons.append(
            Reason("WORKFLOW_THRESHOLD_NOT_MET", f"审查评分 {report.score} 分未达审批门槛（需 ≥ {SCORE_THRESHOLD}）")
        )

    return ApprovalEligibility(not reasons, reasons, report=report, task=task)

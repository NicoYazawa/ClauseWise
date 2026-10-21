"""AI review service (design doc 3.2): dual-track review via task state machine + multi-agent graph (LangGraph).

- Core execution delegated to app/agents/review_graph: Planner -> Rule Auditor (hard checks, zero token)
  -> Clause Reviewer xN (ReAct tool loop, concurrency <= 8) -> Reviewer (verify/degrade/drop) -> Report Writer
- Scoring unchanged: only the rule engine's deterministic conclusions are scored and blocking (100-40H-15M-5L, floor 0);
  LLM findings are AI reference suggestions; data contract (RiskFinding / ReviewReport / report_json) matches the old pipeline
- Agent collaboration traced in agent_trace (frontend timeline)
- Zombie recovery: service restart / no Worker leaves pending/running hanging -> auto-mark failed and roll back contract status
"""
import hashlib
import re
from datetime import datetime
from typing import Literal

from loguru import logger
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.ai import llm_client
from app.ai.prompt_manager import SCENE_REVIEW, get_active_prompt
from app.models.contract import Contract, ContractClause, ContractVersion
from app.models.knowledge import ContractTemplate, Notification
from app.models.review import ReviewReport, ReviewTask, RiskFinding

CONTRACT_TYPE_LABELS = {
    "purchase": "采购合同", "sales": "销售合同", "labor": "劳务合同",
    "lease": "租赁合同", "nda": "保密协议", "other": "其他合同",
}

VALID_LEVELS = {"high", "medium", "low", "none"}

# ===================== RAG soft validation (LLM): structured-output Schema (reused by multi-agent graph sub-agents) =====================


class LlmRiskPoint(BaseModel):
    original_text: str = ""
    issue: str = ""
    legal_basis: str | None = None
    suggestion: str = ""
    suggested_text: str | None = None


class LlmClauseResult(BaseModel):
    """Model risk verdict: the risk level must be a lowercase enum value; a non-none verdict must give at least one risk point with a description.
    Malformed output is rejected outright (counted as a failed retry / missed audit) and must never be silently treated as "no risk"."""

    risk_level: Literal["high", "medium", "low", "none"] = "none"
    risk_type: str = ""
    risk_points: list[LlmRiskPoint] = Field(default_factory=list)

    @model_validator(mode="after")
    def _require_points_for_risk(self):
        if self.risk_level != "none":
            if not self.risk_points or not any((p.issue or "").strip() for p in self.risk_points):
                raise ValueError("risk_level 非 none 时必须提供至少一条包含 issue 的 risk_points")
        return self


def version_content_hash(db: Session, version_id: int) -> str:
    """Content fingerprint of the review target: clause bodies joined in id order and hashed with SHA-256. The report binds to "the exact content that was reviewed" via this hash."""
    from app.models.contract import ContractClause as _Clause

    rows = (
        db.query(_Clause.content)
        .filter(_Clause.version_id == version_id)
        .order_by(_Clause.id)
        .all()
    )
    digest = hashlib.sha256()
    for (content,) in rows:
        digest.update((content or "").encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def calc_score(high: int, medium: int, low: int) -> int:
    return max(0, 100 - 40 * high - 15 * medium - 5 * low)


# ===================== Rule engine (hard validation) =====================


def run_rule_engine(db: Session, contract: Contract, clauses: list[ContractClause]) -> list[dict]:
    """Deterministic rules: missing required clauses (template required), missing dispute resolution, personal-injury liability exclusion, penalty exceeding the hint line."""
    findings: list[dict] = []
    clause_nos = "、".join(c.clause_no for c in clauses)

    # 1. missing dispute-resolution clause -> high (blocking)
    has_dispute = any(c.clause_type == "争议解决" or re.search(r"争议|管辖|仲裁|诉讼", c.content) for c in clauses)
    if not has_dispute:
        findings.append(
            {
                "clause_no": "-",
                "clause_id": 0,
                "risk_level": "high",
                "risk_type": "条款缺失",
                "issue": "合同缺少书面争议解决条款，发生纠纷时管辖不明，属于必备条款缺失（阻断项）。",
                "original_text": f"（现有条款：{clause_nos[:200]}，均未约定争议解决方式）",
                "legal_basis": "企业模板库《通用争议解决条款》- 必备条款：缺失即判定高风险。",
                "suggestion": "建议补充：「因本合同发生的争议，双方应友好协商；协商不成的，提交合同签订地有管辖权的人民法院诉讼解决。」",
                "suggested_text": "因本合同发生的争议，双方应友好协商；协商不成的，提交合同签订地有管辖权的人民法院诉讼解决。",
                "rag_hits": ["规则引用 · 企业模板《通用争议解决条款》"],
                "source": "rule",
            }
        )

    # 2. check required-clause absence by type (template required level)
    templates = (
        db.query(ContractTemplate)
        .filter(ContractTemplate.contract_type == contract.contract_type, ContractTemplate.clause_level == "required")
        .all()
    )
    for tpl in templates:
        keywords = _template_keywords(tpl.name)
        hit = any(any(k in c.content for k in keywords) for c in clauses)
        if not hit:
            findings.append(
                {
                    "clause_no": "-",
                    "clause_id": 0,
                    "risk_level": "medium",
                    "risk_type": "条款缺失",
                    "issue": f"按企业模板（{CONTRACT_TYPE_LABELS.get(contract.contract_type, contract.contract_type)} v{tpl.version}），缺少必备条款「{tpl.name}」。",
                    "original_text": f"（模板标准条款：{tpl.content[:120]}……）",
                    "legal_basis": f"企业模板库《{tpl.name}》（{contract.contract_type} v{tpl.version}）- 必备条款。",
                    "suggestion": f"建议补充该条款，参考模板表述：{tpl.content[:150]}",
                    "suggested_text": tpl.content,
                    "rag_hits": [f"规则引用 · 企业模板《{tpl.name}》（{contract.contract_type} v{tpl.version}）"],
                    "source": "rule",
                }
            )

    # 3. per-clause hard rules
    for cl in clauses:
        # 3.1 personal-injury liability exclusion -> high (illegal/void)
        if re.search(r"(人身|人身损害|伤亡|安全).{0,20}(无关|不承担|免责|概不负责)", cl.content) or re.search(
            r"(一切|全部).{0,10}(损失|损害|伤亡).{0,10}(与.{1,10}无关|不承担)", cl.content
        ):
            findings.append(
                {
                    "clause_no": cl.clause_no,
                    "clause_id": cl.id,
                    "risk_level": "high",
                    "risk_type": "违法无效",
                    "issue": "免除人身损害责任的免责条款违反法律强制性规定，自始无效（《民法典》第五百零六条）。",
                    "original_text": cl.content[:300],
                    "legal_basis": "《民法典》第五百零六条：合同中的下列免责条款无效：（一）造成对方人身损害的；（二）因故意或者重大过失造成对方财产损失的。",
                    "suggestion": "建议删除该免责表述，改为双方依法各自承担安全保障责任与工伤保险义务。",
                    "suggested_text": "双方依据相关安全生产法律法规，各自承担相应的安全保障责任与工伤保险义务；因一方过错造成损害的，依法承担相应赔偿责任。",
                    "rag_hits": ["规则引用 · 《民法典》第五百零六条"],
                    "source": "rule",
                }
            )
        # 3.2 penalty-ratio hint line: only percentages bound to a penalty-type obligation
        # (违约金/滞纳金/罚款/赔偿金) within the same statement segment count — unrelated ratios
        # (e.g. 预付款 50%) must never be reported as 违约金比例.
        for segment in re.split(r"[。；;，,、]", cl.content):
            if not re.search(r"违约金|滞纳金|罚款|赔偿金", segment):
                continue
            for pct in re.findall(r"(\d+(?:\.\d+)?)\s*%", segment):
                val = float(pct)
                if val > 30:
                    findings.append(
                        {
                            "clause_no": cl.clause_no,
                            "clause_id": cl.id,
                            "risk_level": "medium",
                            "risk_type": "权责不对等",
                            "issue": f"违约金比例 {pct}% 超过合同标的额 30% 提示线，诉讼中可能被认定「过分高于损失」而遭司法调减（指导案例 64 号）。",
                            "original_text": cl.content[:300],
                            "legal_basis": "《民法典》第五百八十五条 + 指导案例 64 号（超过损失 30% 一般认定为过分高于损失）。",
                            "suggestion": "建议将违约金比例下调至不超过合同总价的 10%~20%，或约定按日万分之五累计并设置封顶。",
                            "suggested_text": "任一方违约的，每逾期一日按合同总价的0.05%向对方支付违约金，累计不超过合同总价的10%；违约金不足以弥补实际损失的，按实际损失赔偿。",
                            "rag_hits": ["规则引用 · 《民法典》第五百八十五条", "规则引用 · 指导案例 64 号"],
                            "source": "rule",
                        }
                    )
                    break
            else:
                continue
            break
        # 3.3 unilateral unlimited liability / unilateral interpretation right -> high
        unilateral_power = re.search(
            r"(随时|有权随时).{0,15}(退回|解除|终止).{0,15}(不承担任何责任|且不承担)", cl.content
        )
        unilateral_interp = re.search(r"由(甲方|乙方)单方(解释|认定|决定)", cl.content)
        if unilateral_power or unilateral_interp:
            # Provide complete rewrite text per matched branch (for the "accept suggestion -> auto-amend clause" loop)
            if unilateral_power:
                suggested = (
                    "一方行使解除、退回等权利的，应提前7日书面通知对方并协商办理交接；"
                    "因未及时通知给对方造成损失的，依法承担赔偿责任。"
                )
            else:
                suggested = (
                    "本合同条款及相关标准理解发生歧义时，双方应友好协商并以书面补充协议确认；"
                    "相关验收、考核结论以双方书面确认的文件为准，一方有异议的，可在3个工作日内申请复核。"
                )
            findings.append(
                {
                    "clause_no": cl.clause_no,
                    "clause_id": cl.id,
                    "risk_level": "high",
                    "risk_type": "权责不对等",
                    "issue": "单方无限权利 / 单方解释权条款显失公平，可能被认定为无效格式条款。",
                    "original_text": cl.content[:300],
                    "legal_basis": "《民法典》第四百九十七条：提供格式条款一方不合理地免除或减轻其责任、加重对方责任、排除对方主要权利的，该条款无效。",
                    "suggestion": "建议改为对等条款：行权应提前书面通知并设置合理期限，验收标准以双方确认的书面文件为准，异议复核机制 3 个工作日。",
                    "suggested_text": suggested,
                    "rag_hits": ["规则引用 · 《民法典》第四百九十七条"],
                    "source": "rule",
                }
            )
    return findings


def _template_keywords(name: str) -> list[str]:
    mapping = {
        "标的与质量": ["标的", "质量", "质保", "规格"],
        "付款": ["付款", "支付", "价款", "结算"],
        "违约责任": ["违约", "违约金"],
        "价款与结算": ["价款", "结算", "付款"],
        "交付与风险转移": ["交付", "风险"],
        "派遣岗位与期限": ["派遣", "岗位"],
        "费用与工资": ["费用", "工资"],
        "租赁物与租金": ["租赁物", "租金"],
        "维修责任": ["维修", "维修责任"],
        "保密信息范围": ["保密信息"],
        "保密期限": ["保密期限", "保密"],
        "违约责任条款": ["违约"],
        "争议解决": ["争议", "仲裁", "诉讼", "管辖"],
    }
    for key, words in mapping.items():
        if key in name:
            return words
    return [name[:4]]


# ===================== Main flow =====================


def _pick_clauses(db: Session, task: ReviewTask) -> list[ContractClause]:
    version_id = task.version_id
    q = db.query(ContractClause).filter(ContractClause.version_id == version_id)
    clauses = q.order_by(ContractClause.id).all()
    if task.task_type == "clause":
        return [c for c in clauses if c.clause_no == (task.clause_no or "")]
    if task.task_type == "diff" and task.base_version_no:
        base_ver = (
            db.query(ContractVersion)
            .filter(
                ContractVersion.contract_id == task.contract_id,
                ContractVersion.version_no == task.base_version_no,
            )
            .first()
        )
        if base_ver:
            from app.utils.diff import text_similarity

            base_clauses = db.query(ContractClause).filter(ContractClause.version_id == base_ver.id).all()
            base_by_no = {c.clause_no: c for c in base_clauses}
            changed = []
            for c in clauses:
                b = base_by_no.get(c.clause_no)
                if b is None or text_similarity(b.content, c.content) < 0.98:
                    changed.append(c)
            return changed
    return clauses


def _dedup(findings: list[dict]) -> list[dict]:
    """Merge and dedupe dual-track results (source=rule first; dedupe by clause_no+issue prefix)."""
    seen: set[str] = set()
    out = []
    for f in sorted(findings, key=lambda x: 0 if x["source"] == "rule" else 1):
        key = f"{f['clause_no']}|{f['issue'][:40]}"
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def _is_current_version_task(db: Session, task: ReviewTask, contract: Contract) -> bool:
    """Whether the version bound to the task is still the contract's current version (after a concurrent new-version upload, the old task's conclusion must not overwrite the whole-contract status)."""
    if not task.version_id:
        return False
    current_row = (
        db.query(ContractVersion)
        .filter(
            ContractVersion.contract_id == contract.id,
            ContractVersion.version_no == contract.current_version,
        )
        .first()
    )
    return current_row is not None and current_row.id == task.version_id


def run_review(db: Session, task_id: int) -> None:
    """Review task main flow (shared by Celery / thread pool): progress written to DB for frontend polling."""
    task = db.get(ReviewTask, task_id)
    if not task:
        return
    # Atomic claim (pending/failed -> running): within the dispatch-degrade window the same task may exist in both the Worker queue and thread pool; only one side may execute
    claimed = (
        db.execute(
            update(ReviewTask)
            .where(ReviewTask.id == task_id, ReviewTask.status.in_(("pending", "failed")))  # type: ignore[arg-type]
            .values(status="running", progress=5)
            .execution_options(synchronize_session=False)
        ).rowcount
    )
    if not claimed:
        logger.warning(f"review task {task_id} already claimed (status={task.status}), skip")
        return
    task.status = "running"
    task.progress = 5
    contract = db.get(Contract, task.contract_id)
    started = datetime.now()
    if contract and task.task_type == "full" and _is_current_version_task(db, task, contract):
        contract.status = "under_review"
        contract.updated_at = started
    db.commit()

    try:
        llm_client.ensure_llm_configured()
        clauses = _pick_clauses(db, task)
        if not clauses:
            raise llm_client.LLMError("未找到可审查的条款（请确认解析已完成）")

        prompt_tpl = get_active_prompt(db, SCENE_REVIEW)
        task.prompt_version = prompt_tpl.version
        db.commit()

        # ===== Multi-agent collaboration graph (LangGraph): Planner -> Rule Auditor -> Clause Reviewer xN -> Reviewer -> Report Writer =====
        # Data contract matches the old pipeline; collaboration steps traced in agent_trace (frontend "Agent collaboration" timeline)
        from app.agents.review_graph import run_review_graph  # lazy import to avoid circular dependency

        def _progress(p: int) -> None:
            task.progress = p
            db.commit()

        graph_out = run_review_graph(
            db,
            task_id=task.id,
            contract=contract,
            clauses=clauses,
            prompt_tpl_content=prompt_tpl.content,
            progress_cb=_progress,
        )
        all_findings = graph_out["findings"]
        stats = graph_out["stats"]
        high, medium, low = stats["high"], stats["medium"], stats["low"]
        ai_high, ai_medium, ai_low = stats["ai_high"], stats["ai_medium"], stats["ai_low"]
        score = stats["score"]
        opinion = graph_out["opinion"]
        total_tokens = graph_out["tokens"]
        task.progress = 95
        db.commit()

        db.query(RiskFinding).filter(RiskFinding.task_id == task.id).delete()
        for f in all_findings:
            db.add(
                RiskFinding(
                    task_id=task.id,
                    clause_id=f["clause_id"],
                    clause_no=f["clause_no"],
                    risk_level=f["risk_level"],
                    risk_type=f["risk_type"],
                    issue=f["issue"],
                    original_text=f["original_text"],
                    legal_basis=f["legal_basis"],
                    suggestion=f["suggestion"],
                    suggested_text=f.get("suggested_text"),
                    rag_hits=f.get("rag_hits"),
                    source=f["source"],
                    status="open",
                )
            )
        db.flush()

        # Scoring & blocking follow the graph's deterministic calc (only rule-source counts; LLM findings are AI suggestions);
        # still stored/shown normally, can be adopted for auto-amend, but not scored/blocked
        completed = datetime.now()
        duration_ms = int((completed - started).total_seconds() * 1000)

        db.query(ReviewReport).filter(ReviewReport.task_id == task.id).delete()
        content_hash = version_content_hash(db, task.version_id) if task.version_id else None
        # Whether the task's version is still the contract's current version: after a concurrent new-version upload, an old task's conclusion must not rewrite the overall status
        is_current_version = bool(contract) and _is_current_version_task(db, task, contract)
        needs_re_review = not is_current_version
        report = ReviewReport(
            task_id=task.id,
            contract_id=task.contract_id,
            version_id=task.version_id,
            content_hash=content_hash,
            score=score,
            high_count=high,
            medium_count=medium,
            low_count=low,
            overall_opinion=opinion,
            report_json={
                "summary": {
                    "high": high + ai_high,
                    "medium": medium + ai_medium,
                    "low": low + ai_low,
                    "score": score,
                    "blockingHigh": high,
                    "aiHigh": ai_high,
                    "aiMedium": ai_medium,
                    "aiLow": ai_low,
                    # > 0 when some clause reviews failed/skipped, for frontend/API to flag an incomplete report
                    "failedClauses": stats.get("failed_clauses", 0),
                    # Review target is no longer the current version (or it was a partial review): the report cannot serve as the approval basis for the whole contract
                    "needsReReview": needs_re_review,
                    "taskType": task.task_type,
                },
                "overallOpinion": opinion,
                "findings": all_findings,
            },
            created_at=completed,
        )
        db.add(report)

        task.status = "completed"
        task.progress = 100
        # Must clear previous failure trace on successful retry, otherwise completed tasks still show old errors
        task.error_msg = None
        task.completed_at = completed
        task.duration_ms = duration_ms
        task.tokens_used = total_tokens
        task.model_version = llm_client.current_model()
        # Overall approval eligibility is written back only by a "full-text review of the current version": single-clause/incremental/old-version reviews do not change the overall status
        if contract and task.task_type == "full" and is_current_version:
            contract.status = "review_blocked" if high > 0 else "review_passed"
            contract.updated_at = completed
        db.commit()

        # Metrics: terminal-state count + end-to-end latency
        try:
            from app.core.metrics import REVIEW_DURATION, REVIEW_TASKS

            REVIEW_TASKS.labels(status="completed").inc()
            REVIEW_DURATION.observe(duration_ms / 1000)
        except Exception as metric_err:  # noqa: BLE001  metrics failure must not affect main flow
            logger.warning(f"metrics failed: {metric_err}")

        # Notification + report-summary vectorization (failure does not block)
        try:
            db.add(
                Notification(
                    type="review_done",
                    user_id=contract.owner_id if contract else None,  # direct notification to the contract owner
                    title="AI 审查完成" + ("（高风险阻断）" if high > 0 else ""),
                    content=(
                        f"「{contract.title}」审查完成：规则评分 {score} 分，"
                        f"阻断项 {high} 项" + ("，已阻断进入审批，请修改后重审。" if high > 0 else "，可发起审批。")
                        + (f" AI 参考发现 高{ai_high}/中{ai_medium}/低{ai_low}。" if (ai_high + ai_medium + ai_low) else "")
                    ),
                    created_at=completed,
                )
            )
            db.commit()
        except Exception as e:
            logger.warning(f"notification failed: {e}")

        try:
            from app.ai.rag import index_report_summary

            summary_text = f"{contract.title} 审查报告：{opinion}；风险：高{high}/中{medium}/低{low}，评分 {score}。"
            es_doc = index_report_summary(report.id, contract.title, summary_text)
            if es_doc:
                report.es_doc_id = es_doc
                db.commit()
        except Exception as e:
            logger.warning(f"report index failed: {e}")

        logger.info(f"review task {task_id} completed: score={score}, findings={len(all_findings)}")
    except Exception as e:  # noqa: BLE001
        db.rollback()
        task = db.get(ReviewTask, task_id)
        task.status = "failed"
        task.error_msg = str(e)[:500]
        # Failure rollback also applies only to "full-text review of the current version"; failures of old/partial tasks do not affect the overall status
        if contract and task and task.task_type == "full" and _is_current_version_task(db, task, contract):
            contract.status = "parsed"  # roll back to re-reviewable status
            contract.updated_at = datetime.now()
        db.commit()
        logger.error(f"review task {task_id} failed: {e}")
        try:
            from app.core.metrics import REVIEW_TASKS

            REVIEW_TASKS.labels(status="failed").inc()
        except Exception:  # noqa: BLE001
            pass
        # Alert outbound (sync send, rate-limited per task; no-op when unconfigured)
        try:
            from app.core.alerting import notify_task_failure

            notify_task_failure(
                "review",
                task_id,
                f"{contract.title if contract else '-'}（任务类型 {task.task_type}）",
                e,
            )
        except Exception as alert_err:  # noqa: BLE001  alert failure must not affect main flow
            logger.warning(f"review alert failed: {alert_err}")
        raise


# ===================== Zombie task recovery (self-heal after restart / no Worker) =====================

PENDING_STALE_MINUTES = 10  # "dead" threshold when submitted but never consumed (e.g. Redis up but Celery Worker not started)
RUNNING_STALE_MINUTES = 30  # "dead" threshold when stuck running (covers the longest per-clause LLM retry chain)
PARSING_STALE_MINUTES = 30  # "dead" threshold when stuck parsing (covers multi-page visual OCR chain for scanned docs)


def stale_reason(t: ReviewTask, now: datetime) -> str | None:
    """Decide whether a review task is a zombie (long-pending/running with no progress); return the reason, or None if not."""
    if t.status == "pending" and t.created_at and (now - t.created_at).total_seconds() > PENDING_STALE_MINUTES * 60:
        return (
            f"任务提交超过 {PENDING_STALE_MINUTES} 分钟仍未开始执行：调度器无可用 Worker 消费队列"
            "（Redis 可用时需另开窗口执行 .\\scripts\\start.ps1 worker），已自动回收，可重新发起审查。"
        )
    if t.status == "running" and t.created_at and (now - t.created_at).total_seconds() > RUNNING_STALE_MINUTES * 60:
        return "审查任务长时间未完成（服务重启或执行中断），已自动回收，可重新发起审查。"
    return None


def recover_task(db: Session, t: ReviewTask, reason: str) -> None:
    """Recover a single zombie review task and roll back contract status (consistent with run_review failure path)."""
    t.status = "failed"
    t.error_msg = reason[:500]
    t.completed_at = datetime.now()
    contract = db.get(Contract, t.contract_id)
    if contract and contract.status == "under_review":
        still_running = (
            db.query(ReviewTask)
            .filter(
                ReviewTask.contract_id == t.contract_id,
                ReviewTask.id != t.id,
                ReviewTask.status.in_(("pending", "running")),  # type: ignore[arg-type]
            )
            .count()
        )
        if not still_running:
            contract.status = "parsed"  # roll back to re-reviewable status (bypass state machine, consistent with failure rollback path)
            contract.updated_at = datetime.now()
    db.commit()
    logger.warning(f"review task {t.id} recovered as stale: {reason[:120]}")


def recover_stale_tasks(db: Session) -> int:
    """Bulk zombie recovery (startup recovery + periodic scan):

    - review task pending/running timeout -> failed, contract under_review -> parsed
    - parse version parsing timeout -> failed, contract parsing -> parse_failed (can re-parse)
    return the recovery count.
    """
    now = datetime.now()
    count = 0
    for t in db.query(ReviewTask).filter(ReviewTask.status.in_(("pending", "running"))).all():  # type: ignore[arg-type]
        reason = stale_reason(t, now)
        if reason:
            recover_task(db, t, reason)
            count += 1

    for v in (
        db.query(ContractVersion)
        .filter(ContractVersion.parse_status == "parsing")
        .all()
    ):
        if v.created_at and (now - v.created_at).total_seconds() > PARSING_STALE_MINUTES * 60:
            v.parse_status = "failed"
            v.parse_error = (
                f"解析任务超过 {PARSING_STALE_MINUTES} 分钟未完成（服务重启或无可用 Worker），已自动回收，可重新解析。"
            )
            contract = db.get(Contract, v.contract_id)
            if contract and contract.status == "parsing":
                contract.status = "parse_failed"
                contract.updated_at = now
            count += 1
            logger.warning(f"parse version {v.id} recovered as stale")
    if count:
        db.commit()
    return count

"""Agent toolset: wrap existing service capabilities as LangChain tools (callable by the ReAct tool-call loop).

Conventions:
- Tool signatures take str args (ReAct models pass strings); parse robustly inside
- DB tools use a short SessionLocal session, never share the caller's (Celery/request) session across threads
- Return formatted text (LLM-readable); retrieval tool output matches the old prompt-injection format for reuse
"""
from loguru import logger

from app.ai.rag import hybrid_search_knowledge
from app.db.session import SessionLocal

# Chinese type labels -> type codes (model may pass Chinese)
_TYPE_ALIASES = {
    "purchase": "purchase", "sales": "sales", "labor": "labor", "lease": "lease", "nda": "nda", "other": "other",
    "采购": "purchase", "采购合同": "purchase", "销售": "sales", "销售合同": "sales",
    "劳务": "labor", "劳务合同": "labor", "租赁": "lease", "租赁合同": "lease",
    "保密": "nda", "保密协议": "nda", "其他": "other", "其他合同": "other",
}


def _normalize_type(contract_type: str) -> str:
    key = (contract_type or "").strip().lower()
    return _TYPE_ALIASES.get(key, "other")


def _parse_id(value: str) -> int:
    try:
        return int(str(value).strip().rstrip("号.").lstrip("#hHT-＿ "))
    except (ValueError, TypeError):
        return 0


def search_legal_knowledge(query: str) -> str:
    """Retrieve relevant entries from the enterprise legal knowledge base (laws/cases/template clauses).

    Args:
        query: search question or clause description (e.g. "违约金上限 相关规定", "人身损害免责条款 效力")
    """
    hits = hybrid_search_knowledge(query, top_k=6)
    if not hits:
        return "（知识库未命中相关依据）"
    return "\n".join(f"- [{h.kind}] {h.title}：{h.snippet[:200]}" for h in hits)


def get_contract_templates(contract_type: str) -> str:
    """List enterprise standard template clauses by contract type (with required/recommended level and standard wording).

    Args:
        contract_type: contract type code, purchase/sales/labor/lease/nda/other (also accepts Chinese like "采购合同")
    """
    from app.models.knowledge import ContractTemplate

    db = SessionLocal()
    try:
        rows = (
            db.query(ContractTemplate)
            .filter(ContractTemplate.contract_type == _normalize_type(contract_type))
            .order_by(ContractTemplate.clause_level, ContractTemplate.id)
            .all()
        )
        if not rows:
            return f"（未找到 {_normalize_type(contract_type)} 类型的企业模板）"
        return "\n".join(
            f"- [{r.clause_level}] {r.name}（v{r.version}）：{r.content[:160]}" for r in rows
        )
    finally:
        db.close()


def get_contract_info(contract_id: str, *, allowed_contract_id: int | None = None) -> str:
    """Query basic contract info (title/type/counterparty/amount/status).

    Args:
        contract_id: numeric contract id (e.g. "12" or "#12")
    """
    from app.models.contract import Contract

    cid = _parse_id(contract_id)
    if allowed_contract_id is None or cid != allowed_contract_id:
        return "（权限不足：仅可查询当前审查合同）"
    db = SessionLocal()
    try:
        c = db.get(Contract, cid)
        if not c:
            return f"（合同 {cid} 不存在）"
        return (
            f"合同 #{c.id}《{c.title}》：类型 {c.contract_type}，相对方 {c.counterparty_name}，"
            f"金额 {c.amount} 元，状态 {c.status}，当前版本 v{c.current_version}。"
        )
    finally:
        db.close()


def get_contract_clauses(contract_id: str, *, allowed_contract_id: int | None = None) -> str:
    """Query all clauses of the contract's current version (clause no/type/text) for per-clause checking.

    Args:
        contract_id: numeric contract id
    """
    from app.models.contract import Contract, ContractClause, ContractVersion

    cid = _parse_id(contract_id)
    if allowed_contract_id is None or cid != allowed_contract_id:
        return "（权限不足：仅可查询当前审查合同）"
    db = SessionLocal()
    try:
        c = db.get(Contract, cid)
        if not c:
            return f"（合同 {cid} 不存在）"
        ver = (
            db.query(ContractVersion)
            .filter(ContractVersion.contract_id == cid, ContractVersion.version_no == c.current_version)
            .first()
        )
        if not ver:
            return "（该合同暂无已解析条款）"
        clauses = (
            db.query(ContractClause)
            .filter(ContractClause.version_id == ver.id, ContractClause.contract_id == cid)
            .order_by(ContractClause.id)
            .all()
        )
        return "\n".join(f"- {x.clause_no}（{x.clause_type}）：{x.content[:200]}" for x in clauses)
    finally:
        db.close()


def get_history_review_reports(contract_id: str, *, allowed_contract_id: int | None = None) -> str:
    """Query a contract's historical AI review report summaries (score/risk counts/review opinion).

    Args:
        contract_id: numeric contract id
    """
    from app.models.review import ReviewReport

    cid = _parse_id(contract_id)
    if allowed_contract_id is None or cid != allowed_contract_id:
        return "（权限不足：仅可查询当前审查合同）"
    db = SessionLocal()
    try:
        rows = (
            db.query(ReviewReport)
            .filter(ReviewReport.contract_id == cid)
            .order_by(ReviewReport.id.desc())
            .limit(5)
            .all()
        )
        if not rows:
            return "（该合同暂无历史审查报告）"
        return "\n".join(
            f"- 报告 #{r.id}（任务 {r.task_id}）：评分 {r.score}，高/中/低 {r.high_count}/{r.medium_count}/{r.low_count}；{r.overall_opinion[:120]}"
            for r in rows
        )
    finally:
        db.close()


def make_langchain_tools(*, contract_id: int | None = None):
    """Wrap the pure functions above as a list of LangChain StructuredTools (for ReAct sub-agents).

    Decoupled from the @tool decorator (avoids importing langchain at module load); pure functions are also reusable by deterministic nodes.
    """
    from langchain_core.tools import StructuredTool

    def bound(fn):
        def invoke(contract_id: str) -> str:
            return fn(contract_id, allowed_contract_id=allowed_id)

        invoke.__name__ = fn.__name__
        invoke.__doc__ = fn.__doc__
        return invoke

    allowed_id = contract_id
    specs = [search_legal_knowledge, get_contract_templates,
             bound(get_contract_info), bound(get_contract_clauses), bound(get_history_review_reports)]
    return [StructuredTool.from_function(func=f, description=f.__doc__.split("\n")[0] if f.__doc__ else f.__name__) for f in specs]


TOOL_NAMES = [
    "search_legal_knowledge",
    "get_contract_templates",
    "get_contract_info",
    "get_contract_clauses",
    "get_history_review_reports",
]

logger.debug("agent tools ready: %s", TOOL_NAMES)

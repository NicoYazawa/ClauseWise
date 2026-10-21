"""Contract-review multi-agent collaboration graph (LangGraph orchestration):

START -> planner (planner)            LLM structured output: review focus / risk hints
      -> rule_auditor (rule auditor)   deterministic rule engine hard-checks (zero token, sole basis for scoring & blocking)
      -> clause_reviewers (clause reviewers xN)  concurrent ReAct sub-agents (tool loop: knowledge retrieval / template lookup)
      -> verifier (verifier)           ReAct tool loop to verify LLM high/medium risk findings: confirm/downgrade/drop
      -> reporter (reporter)           aggregates and produces the review opinion (score still computed by deterministic code)
      -> END

Design notes:
- Graph state (ReviewState) is the shared memory (blackboard) between agents: plan points, rule findings,
  clause findings, and verification conclusions are passed along nodes; the whole flow is recorded via
  TraceRecorder into agent_trace.
- Linear topology: nodes execute sequentially within the calling thread (the rule engine reuses the caller's
  DB session; the ORM must not cross threads). Concurrency happens inside the clause_reviewers node -- N ReAct
  sub-agents run concurrently (<=8) via run_parallel.
- Sub-agent final replies are extracted as JSON and validated with Pydantic; on failure, one retry is allowed
  (consistent with the legacy pipeline strategy).
- Any agent failure has a deterministic fallback: planner failure uses default points, verifier failure falls
  back to _dedup merge, reporter failure uses a template opinion -- ensuring the review task state machine is
  unaffected.
"""
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypedDict

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from loguru import logger
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.agents import llm as agent_llm
from app.agents import tools as agent_tools
from app.agents.registry import AgentSpec, register_agent
from app.agents.trace import TraceRecorder
from app.ai import llm_client
from app.ai.prompt_manager import render_prompt
from app.core.config import settings
from app.models.contract import Contract, ContractClause
from app.services.review_service import (
    CONTRACT_TYPE_LABELS,
    LlmClauseResult,
    LlmRiskPoint,
    _dedup,
    calc_score,
    run_rule_engine,
)

# ===================== Agent registration (registered into the registry on import) =====================

PLANNER_SPEC = register_agent(
    AgentSpec(
        name="review_planner", role="规划者", graph="review_graph", kind="structured",
        description="分解审查任务：按合同类型/金额/条款结构生成审查要点与风险提示，分发给条款审查员",
        desc_key="data.agentDesc.review_planner",
    )
)
RULE_AUDITOR_SPEC = register_agent(
    AgentSpec(
        name="rule_auditor", role="规则审计员", graph="review_graph", kind="deterministic",
        description="规则引擎硬校验（必备条款缺失/人身损害免责/违约金提示线等），确定性结论，零 token",
        desc_key="data.agentDesc.rule_auditor",
    )
)
CLAUSE_REVIEWER_SPEC = register_agent(
    AgentSpec(
        name="clause_reviewer", role="条款审查员", graph="review_graph", kind="llm",
        tools=["search_legal_knowledge", "get_contract_templates"],
        description="逐条款 ReAct 子代理：通过工具调用循环检索法律依据，产出结构化风险发现，N 条款并发审查",
        desc_key="data.agentDesc.clause_reviewer",
    )
)
VERIFIER_SPEC = register_agent(
    AgentSpec(
        name="verifier", role="复核员", graph="review_graph", kind="llm",
        tools=["search_legal_knowledge"],
        description="复核条款审查员的 LLM 高/中风险发现：检索核实依据真实性，确认/降级/剔除并去重",
        desc_key="data.agentDesc.verifier",
    )
)
REPORTER_SPEC = register_agent(
    AgentSpec(
        name="reporter", role="报告撰写员", graph="review_graph", kind="structured",
        description="聚合复核后的发现生成整体审查意见（评分与阻断仍由确定性代码计算，保证可复现）",
        desc_key="data.agentDesc.reporter",
    )
)

# ===================== Structured-output schemas =====================


class ReviewPlan(BaseModel):
    summary: str = ""
    focus_points: list[str] = Field(default_factory=list)
    risk_hints: list[str] = Field(default_factory=list)


class Verdict(BaseModel):
    index: int
    verdict: str  # confirm / downgrade / drop
    reason: str = ""


class VerdictList(BaseModel):
    verdicts: list[Verdict] = Field(default_factory=list)


class ReporterOut(BaseModel):
    opinion: str


# ===================== Shared state (blackboard memory) =====================


class ReviewState(TypedDict, total=False):
    contract: dict  # contract meta info (plain values)
    clauses: list[dict]  # clause plain-value list (concurrent threads do not touch the ORM)
    plan: dict
    rule_findings: list[dict]
    llm_findings: list[dict]
    failed_clauses: int  # number of clauses skipped due to review failure ( > 0 on partial degradation)
    verified_findings: list[dict]
    stats: dict
    opinion: str


@dataclass
class _Ctx:
    """Graph-build context: runtime dependencies shared by node closures (a fresh graph is built per task)."""

    db: Session
    task_id: int
    trace: TraceRecorder
    prompt_tpl_content: str
    progress_cb: Callable[[int], None] | None
    contract: Contract | None  # used by rule_auditor (accessed from the main thread)
    clauses: list[ContractClause]
    contract_type: str


# ===================== Common helpers =====================


def _extract_json(text: str) -> dict:
    """Robustly extract JSON from a sub-agent's final reply (tolerates ``` fences and surrounding text)."""
    cleaned = re.sub(r"```(?:json)?", "", str(text)).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("输出中未找到 JSON 对象")
    return json.loads(cleaned[start : end + 1])


def _messages_tokens(messages: list) -> int:
    """Sum token usage across all sub-agent LLM calls (AIMessage.usage_metadata)."""
    total = 0
    for m in messages:
        um = getattr(m, "usage_metadata", None)
        if isinstance(um, dict):
            total += int(um.get("total_tokens") or 0)
    return total


def _tool_calls_summary(messages: list) -> list[dict]:
    """Extract the tool-call loop trajectory (args + result summary) for the trace timeline."""
    args_by_id: dict[str, dict] = {}
    for m in messages:
        for tc in getattr(m, "tool_calls", None) or []:
            args_by_id[tc.get("id") or ""] = tc.get("args") or {}
    calls: list[dict] = []
    for m in messages:
        if isinstance(m, ToolMessage):
            calls.append(
                {
                    "tool": m.name,
                    "args": args_by_id.get(m.tool_call_id),
                    "result": str(m.content)[:160],
                }
            )
    return calls


def _rag_hits_from_messages(messages: list) -> list[str]:
    """Extract hit entry titles from retrieval-tool return text (replaces the rag_hits label of the legacy prefetch)."""
    labels: list[str] = []
    for m in messages:
        if isinstance(m, ToolMessage) and m.name == "search_legal_knowledge":
            for _kind, title in re.findall(r"- \[(\w+)\] ([^：]+)：", str(m.content)):
                label = title.strip()
                if label and label not in labels:
                    labels.append(label)
    return labels[:6]


# ===================== Node 1: planner =====================

PLANNER_SYSTEM = (
    "你是一名具有丰富中国企业合同审查与合规经验的资深法务，担任合同合规审查团队的任务规划 Agent（planner）。"
    "根据合同元信息为条款审查员们制定审查计划：聚焦该类合同最关键的合规维度与常见风险模式。"
    '仅输出 JSON：{"summary": "一句话计划", "focus_points": ["审查要点", ...], "risk_hints": ["风险提示", ...]}'
)


def _node_planner(ctx: _Ctx):
    def planner(state: ReviewState) -> dict:
        t0 = time.time()
        contract = state["contract"]
        label = CONTRACT_TYPE_LABELS.get(ctx.contract_type, ctx.contract_type)
        plan: ReviewPlan
        tokens = 0
        try:
            user_prompt = (
                f"[待审合同]\n标题：{contract.get('title', '-')}\n类型：{label}\n"
                f"金额：{contract.get('amount', 0)} 元\n已解析条款：{len(state['clauses'])} 条\n"
                f"条款类型分布：{'、'.join(contract.get('clause_types', [])[:8])}\n\n"
                f"[任务] 生成 3~5 条审查要点（focus_points）与 2~4 条风险提示（risk_hints），"
                "将分发给逐条款审查的 Agent 作为审查重点。"
            )
            raw, tokens = llm_client.chat_json(PLANNER_SYSTEM, user_prompt)
            plan = ReviewPlan.model_validate(raw)
        except Exception as e:  # noqa: BLE001  planner failure degrades to default plan, does not block review
            logger.warning(f"planner degraded to default plan: {e}")
            plan = ReviewPlan(
                summary=f"按{label}通用合规维度审查",
                focus_points=[f"聚焦{label}典型合规风险逐条审查", "核对违约责任与权责对等性", "核对争议解决与必备条款完整性"],
                risk_hints=["免责条款效力", "单方权利与格式条款公平性"],
            )
        plan_dict = {"summary": plan.summary, "focusPoints": plan.focus_points, "riskHints": plan.risk_hints}
        ctx.trace.step(
            "review_planner", "规划者", "plan",
            {"input": {"title": contract.get("title"), "type": label}, "output": plan_dict},
            tokens=tokens, latency_ms=int((time.time() - t0) * 1000),
        )
        if ctx.progress_cb:
            ctx.progress_cb(15)
        return {"plan": plan_dict}

    return planner


# ===================== Node 2: rule auditor (deterministic) =====================


def _node_rule_auditor(ctx: _Ctx):
    def rule_auditor(state: ReviewState) -> dict:
        t0 = time.time()
        findings = run_rule_engine(ctx.db, ctx.contract, ctx.clauses) if ctx.contract else []
        ctx.trace.step(
            "rule_auditor", "规则审计员", "decision",
            {
                "summary": f"规则引擎硬校验命中 {len(findings)} 项确定性发现（评分与阻断唯一依据）",
                "findings": [
                    {"clauseNo": f["clause_no"], "level": f["risk_level"], "type": f["risk_type"], "issue": f["issue"][:80]}
                    for f in findings
                ],
            },
            latency_ms=int((time.time() - t0) * 1000),
        )
        if ctx.progress_cb:
            ctx.progress_cb(25)
        return {"rule_findings": findings}

    return rule_auditor


# ===================== Node 3: clause reviewers xN (concurrent ReAct tool loop) =====================

CLAUSE_REVIEWER_SYSTEM = """你是一名具有丰富中国企业合同审查经验的资深合规法务，担任合同条款合规审查员 Agent，负责对单条合同条款做深度合规审查。

工作流程（工具调用循环）：
1. 必须先调用 search_legal_knowledge 工具，检索与本条款相关的法条/案例/企业模板（查询词＝条款类型＋关键表述，如「违约金 上限 调减」）；
2. 需要对照企业标准条款时，再调用 get_contract_templates 工具（传入合同类型代码）；
3. 结合检索结果与规划者要点出具结论；检索未命中时可依据常识法务经验，但 legal_basis 必须填 null，不得编造；
4. 工具调用总数不超过 4 次，达到上限后必须立即输出最终 JSON，不要再发起新的工具调用。

最终回复只输出 JSON（不要输出其他文字）：
{"risk_level": "high|medium|low|none", "risk_type": "风险类型", "risk_points": [{"original_text": "原文摘录", "issue": "风险描述", "legal_basis": "引用检索到的条文编号或 null", "suggestion": "具体修改建议", "suggested_text": "改写后的完整条款文本"}]}

判定基准：high＝违法无效/严重权责失衡；medium＝明显不利或缺失关键保障；low＝表述瑕疵；none＝无风险。"""


def _node_clause_reviewers(ctx: _Ctx):
    label = CONTRACT_TYPE_LABELS.get(ctx.contract_type, ctx.contract_type)
    agent = create_agent(
        agent_llm.get_chat_model(),
        tools=agent_tools.make_langchain_tools(contract_id=ctx.contract.id if ctx.contract else None),
        system_prompt=CLAUSE_REVIEWER_SYSTEM,
    )

    # Each ReAct tool-call round consumes 2 super-steps (model node + tools node).
    # The legacy value of 8 only allowed ~2 retrieval rounds; one extra retrieval would be
    # misjudged as a "dead loop" and abort the entire review.
    base_limit = max(12, settings.agent_recursion_limit)

    def _review_one(cl: dict, plan: dict) -> tuple[list[dict], int]:
        t0 = time.time()
        focus_hint = ""
        if plan.get("focusPoints") or plan.get("riskHints"):
            focus_hint = (
                "\n\n[规划者审查要点]（可结合到检索查询与判定中）\n"
                + "\n".join(f"- 要点：{p}" for p in (plan.get("focusPoints") or [])[:5])
                + "\n".join(f"- 提示：{h}" for h in (plan.get("riskHints") or [])[:4])
            )
        user_prompt = render_prompt(
            ctx.prompt_tpl_content,
            {
                "contract_type": label,
                "clause_text": f"{cl['clause_no']}（{cl['clause_type']}）：{cl['content']}",
                "rag_context": "（由你通过 search_legal_knowledge 工具自行检索后引用）",
            },
        ) + focus_hint
        limit = base_limit
        last_err: Exception | None = None
        for attempt in range(2):  # retry once on JSON validation / recursion-limit errors
            try:
                result = agent.invoke(
                    {"messages": [HumanMessage(content=user_prompt)]},
                    config={"recursion_limit": limit},
                )
                messages = result["messages"]
                parsed = LlmClauseResult.model_validate(_extract_json(messages[-1].content))
                tokens = _messages_tokens(messages)
                tool_calls = _tool_calls_summary(messages)
                rag_hits = _rag_hits_from_messages(messages) or ["（条款审查员 Agent 工具检索，详见协作过程）"]
                findings = _result_to_findings(parsed, cl, rag_hits)
                ctx.trace.step(
                    "clause_reviewer", "条款审查员", "tool_loop",
                    {
                        "clauseNo": cl["clause_no"],
                        "plan": plan.get("summary", ""),
                        "tools": tool_calls,
                        "result": {"riskLevel": parsed.risk_level, "riskType": parsed.risk_type, "points": len(parsed.risk_points)},
                    },
                    tokens=tokens, latency_ms=int((time.time() - t0) * 1000),
                )
                return findings, tokens
            except GraphRecursionError as e:
                # Too many retrieval rounds: raise the budget and demand immediate convergence to avoid repeating the same failure
                last_err = e
                previous, limit = limit, min(limit * 2, 60)
                user_prompt += (
                    "\n\n[注意] 工具调用轮次已达上限。请勿再调用任何工具，"
                    "立即基于已检索到的信息输出最终 JSON。"
                )
                logger.warning(
                    f"clause reviewer recursion limit hit for {cl['clause_no']} "
                    f"(limit {previous}->{limit}), retry with 收敛指令"
                )
            except (ValidationError, ValueError, llm_client.LLMError) as e:
                last_err = e
                user_prompt += (
                    f"\n\n[注意] 上次输出未通过 JSON Schema 校验（{str(e)[:200]}），"
                    "请严格按结构重新输出，risk_points 内每一项必须包含 original_text/issue/legal_basis/suggestion 字段。"
                )
                logger.warning(f"clause reviewer retry ({attempt + 1}/2) for {cl['clause_no']}: {e}")
        raise llm_client.LLMError(f"条款 {cl['clause_no']} 审查失败：{last_err}")

    def _safe_review_one(cl: dict, plan: dict) -> tuple[list[dict], int, bool]:
        """Isolate single-clause failure: one clause anomaly must not fail the whole review task."""
        try:
            findings, tokens = _review_one(cl, plan)
            return findings, tokens, True
        except Exception as e:  # noqa: BLE001  clause-level degradation: skip + record trace, caller tallies failures
            logger.warning(f"clause {cl['clause_no']} review failed, skipped: {e}")
            ctx.trace.step(
                "clause_reviewer", "条款审查员", "decision",
                {
                    "clauseNo": cl["clause_no"],
                    "summary": "该条款审查失败，已跳过（不影响其它条款）",
                    "error": str(e)[:200],
                },
                error=str(e)[:300],
            )
            return [], 0, False

    def clause_reviewers(state: ReviewState) -> dict:
        clauses = state["clauses"]
        plan = state.get("plan") or {}  # shared blackboard: planner points injected into every reviewer
        results = llm_client.run_parallel(lambda cl: _safe_review_one(cl, plan), clauses)
        llm_findings: list[dict] = []
        for i, (findings_i, _tokens_i, _ok) in enumerate(results):
            llm_findings.extend(findings_i)
            if ctx.progress_cb:
                ctx.progress_cb(min(85, 25 + int(60 * (i + 1) / max(1, len(clauses)))))
        failed = sum(1 for _f, _t, ok in results if not ok)
        if failed:
            logger.warning(f"{failed}/{len(clauses)} clause(s) failed and were skipped")
            # A total wipeout must not produce a false "recommend signing" report:
            # running only the rule engine would yield a misleading conclusion.
            if failed == len(clauses):
                raise llm_client.LLMError(
                    f"全部 {len(clauses)} 条条款审查失败（模型或工具链路异常），本次未生成报告"
                )
        return {"llm_findings": llm_findings, "failed_clauses": failed}

    return clause_reviewers


def _result_to_findings(result: LlmClauseResult, cl: dict, rag_hits: list[str]) -> list[dict]:
    """Sub-agent structured result -> risk-finding dict (contract-compatible with legacy llm_result_to_findings, for plain-value clauses)."""
    if result.risk_level not in ("high", "medium", "low"):
        return []
    points = result.risk_points or [LlmRiskPoint(issue=result.risk_type or "存在合规风险", suggestion="")]
    out = []
    for p in points[:4]:
        out.append(
            {
                "clause_no": cl["clause_no"],
                "clause_id": cl["clause_id"],
                "risk_level": result.risk_level,
                "risk_type": (result.risk_type or "合规风险")[:32],
                "issue": p.issue or "存在合规风险",
                "original_text": p.original_text or cl["content"][:300],
                "legal_basis": (p.legal_basis or "（知识库未命中直接依据）")[:1000],
                "suggestion": p.suggestion or "建议结合企业模板标准条款修订。",
                "suggested_text": p.suggested_text,
                "rag_hits": rag_hits,
                "source": "llm",
            }
        )
    return out


# ===================== Node 4: verifier (ReAct tool loop verification) =====================

VERIFIER_SYSTEM = """你是一名具有丰富中国企业合同审查与合规经验的资深法务，担任合同合规审查团队的复核员 Agent（verifier），负责核实条款审查员提交的 LLM 高/中风险发现。

复核方法：
- 对需要查证的发现调用 search_legal_knowledge 工具检索验证：其引用的法律依据是否真实存在、是否与风险描述相关；
- 重点甄别「幻觉依据」「风险夸大」「与条款原文不符」三类问题，并明确指出具体不实之处（如虚构条文编号、依据与风险无关、结论超出条款原文）；
- 全部核实完成后输出裁决。

裁决规则（对每条待核实发现）：
- confirm：依据真实且风险成立，保留原风险等级；
- downgrade：风险存在但等级夸大，降为 low；
- drop：依据不实或明显误判，剔除。

最终回复只输出 JSON（不要输出其他文字）：
{"verdicts": [{"index": 1, "verdict": "confirm|downgrade|drop", "reason": "一句话理由，须点名对应条款编号及具体不实/夸大之处"}]}"""


def _node_verifier(ctx: _Ctx):
    agent = create_agent(
        agent_llm.get_chat_model(),
        tools=[t for t in agent_tools.make_langchain_tools() if t.name == "search_legal_knowledge"],
        system_prompt=VERIFIER_SYSTEM,
    )

    def verifier(state: ReviewState) -> dict:
        t0 = time.time()
        rule_findings = state.get("rule_findings") or []
        llm_findings = state.get("llm_findings") or []
        # Only verify LLM-sourced high/medium (rule conclusions pass deterministically; low-level advice needs no verification)
        candidates = [f for f in llm_findings if f["risk_level"] in ("high", "medium")][:12]

        verified = list(llm_findings)
        if candidates:
            listing = "\n".join(
                f"[{i + 1}] 条款{f['clause_no']}（{f['risk_type']}｜{f['risk_level']}）：{f['issue'][:120]}"
                f"｜声称依据：{(f.get('legal_basis') or '-')[:80]}"
                for i, f in enumerate(candidates)
            )
            user_prompt = (
                f"[待核实发现]（共 {len(candidates)} 条）\n{listing}\n\n"
                "请逐条检索核实并输出裁决 JSON；优先核实 high 级发现，最多检索 6 次。"
            )
            try:
                verdicts: list[Verdict] = []
                tokens = 0
                for attempt in range(2):
                    try:
                        result = agent.invoke(
                            {"messages": [HumanMessage(content=user_prompt)]},
                            config={"recursion_limit": max(24, settings.agent_recursion_limit)},
                        )
                        messages = result["messages"]
                        verdicts = VerdictList.model_validate(_extract_json(messages[-1].content)).verdicts
                        tokens = _messages_tokens(messages)
                        break
                    except (ValidationError, ValueError, llm_client.LLMError) as e:
                        user_prompt += f"\n\n[注意] 上次输出未通过校验（{str(e)[:160]}），请严格按 JSON 结构重新输出。"
                        logger.warning(f"verifier retry ({attempt + 1}/2): {e}")
                if verdicts:
                    verified = _apply_verdicts(llm_findings, candidates, verdicts)
                else:
                    raise llm_client.LLMError("复核员未产出有效裁决")
                ctx.trace.step(
                    "verifier", "复核员", "tool_loop",
                    {
                        "candidates": len(candidates),
                        "tools": _tool_calls_summary(messages),
                        "verdicts": [v.model_dump() for v in verdicts],
                    },
                    tokens=tokens, latency_ms=int((time.time() - t0) * 1000),
                )
            except Exception as e:  # noqa: BLE001  verifier failure degrades to: keep all + deterministic dedup (matches legacy behavior)
                logger.warning(f"verifier degraded to dedup-only: {e}")
                ctx.trace.step(
                    "verifier", "复核员", "decision",
                    {"summary": "复核 Agent 失败，降级为确定性合并去重", "error": str(e)[:200]},
                    latency_ms=int((time.time() - t0) * 1000), error=str(e)[:300],
                )
                verified = list(llm_findings)
        else:
            ctx.trace.step(
                "verifier", "复核员", "decision",
                {"summary": "无 LLM 高/中风险发现，规则结论直接放行", "candidates": 0, "merged": 0},
                latency_ms=int((time.time() - t0) * 1000),
            )

        merged = _dedup(rule_findings + verified)
        ctx.trace.step(
            "verifier", "复核员", "decision",
            {
                "summary": f"复核完成：核实 {len(candidates)} 条，合并去重后 {len(merged)} 项发现",
                "candidates": len(candidates),
                "merged": len(merged),
            },
            latency_ms=int((time.time() - t0) * 1000),
        )
        if ctx.progress_cb:
            ctx.progress_cb(90)
        return {"verified_findings": merged}

    return verifier


def _apply_verdicts(llm_findings: list[dict], candidates: list[dict], verdicts: list[Verdict]) -> list[dict]:
    """Rewrite the finding list per verdict: confirm keeps / downgrade sets low / drop removes (unverified entries keep original state)."""
    by_index = {v.index: v for v in verdicts}
    drop_ids, downgraded = set(), {}
    for i, f in enumerate(candidates, start=1):
        v = by_index.get(i)
        if not v:
            continue
        key = id(f)
        if v.verdict == "drop":
            drop_ids.add(key)
        elif v.verdict == "downgrade":
            downgraded[key] = v.reason
    out = []
    for f in llm_findings:
        key = id(f)
        if key in drop_ids:
            continue
        g = dict(f)
        if key in downgraded:
            g["risk_level"] = "low"
            g["issue"] = f"{g['issue']}（复核降级：{downgraded[key][:60]}）"
        out.append(g)
    return out


# ===================== Node 5: reporter =====================

REPORTER_SYSTEM = (
    "你是一名具有丰富中国企业合同审查与合规经验的资深法务，担任合同合规审查团队的报告撰写 Agent（reporter）。基于审查统计生成整体审查意见："
    "先给结论，再点出关键风险与下一步建议，语气专业克制，80~150 字。"
    '仅输出 JSON：{"opinion": "整体审查意见"}'
)


def _default_opinion(high: int, medium: int, low: int, score: int, ai_high: int, ai_medium: int, ai_low: int) -> str:
    """Deterministic fallback opinion when reporter fails (consistent with legacy template copy)."""
    ai_tail = (
        f"AI 另有参考发现 高{ai_high}/中{ai_medium}/低{ai_low} 项，可在修订或实施阶段参考。"
        if (ai_high + ai_medium + ai_low)
        else ""
    )
    if high > 0:
        return (
            f"不建议签署：规则引擎检出 {high} 项高风险阻断项，必须修改后重新送审。"
            + (f"另有 {medium} 项中风险需一并修订。" if medium else "")
            + (" " + ai_tail if ai_tail else "")
        )
    if score >= 85:
        return (
            f"建议签署：确定性规则未发现阻断项，评分 {score} 分满足审批发起条件（≥ 85 分），可发起审批。"
            + (" " + ai_tail if ai_tail else "")
        )
    return (
        f"建议修改后签署：规则评分 {score} 分未达 85 分审批线，"
        f"建议按修改建议完善后重新送审（中风险 {medium} 项、低风险 {low} 项）。"
    )


def _node_reporter(ctx: _Ctx):
    def reporter(state: ReviewState) -> dict:
        t0 = time.time()
        findings = state["verified_findings"]
        # Scoring basis unchanged: only rule-sourced findings count toward score & blocking; LLM findings are AI advice
        rule_stats = [f for f in findings if f["source"] == "rule"]
        high = sum(1 for f in rule_stats if f["risk_level"] == "high")
        medium = sum(1 for f in rule_stats if f["risk_level"] == "medium")
        low = sum(1 for f in rule_stats if f["risk_level"] == "low")
        ai_high = sum(1 for f in findings if f["risk_level"] == "high" and f["source"] == "llm")
        ai_medium = sum(1 for f in findings if f["risk_level"] == "medium" and f["source"] == "llm")
        ai_low = sum(1 for f in findings if f["risk_level"] == "low" and f["source"] == "llm")
        score = calc_score(high, medium, low)
        label = CONTRACT_TYPE_LABELS.get(ctx.contract_type, ctx.contract_type)
        contract = state["contract"]

        opinion = ""
        tokens = 0
        try:
            user_prompt = (
                f"[审查统计]\n合同：《{contract.get('title', '-')}》（{label}）\n"
                f"规则引擎确定性发现：高 {high} / 中 {medium} / 低 {low} 项；规则评分 {score} 分\n"
                f"AI 参考发现：高 {ai_high} / 中 {ai_medium} / 低 {ai_low} 项（不计分、不阻断）\n\n"
                f"[任务] 撰写整体审查意见（80~150 字）："
                + (
                    "存在高风险阻断项，结论应为「不建议签署」。"
                    if high > 0
                    else ("评分≥85，结论应为「建议签署」。" if score >= 85 else "评分未达 85 分，结论应为「建议修改后签署」。")
                )
            )
            raw, tokens = llm_client.chat_json(REPORTER_SYSTEM, user_prompt)
            opinion = ReporterOut.model_validate(raw).opinion
        except Exception as e:  # noqa: BLE001  writing failure falls back to deterministic template
            logger.warning(f"reporter degraded to default opinion: {e}")
            opinion = ""

        if not opinion.strip():
            opinion = _default_opinion(high, medium, low, score, ai_high, ai_medium, ai_low)

        stats = {
            "high": high, "medium": medium, "low": low,
            "ai_high": ai_high, "ai_medium": ai_medium, "ai_low": ai_low,
            "score": score,
            "failed_clauses": state.get("failed_clauses", 0),
        }
        ctx.trace.step(
            "reporter", "报告撰写员", "report",
            {"stats": stats, "opinion": opinion[:200]},
            tokens=tokens, latency_ms=int((time.time() - t0) * 1000),
        )
        if ctx.progress_cb:
            ctx.progress_cb(95)
        return {"stats": stats, "opinion": opinion}

    return reporter


# ===================== Graph assembly & run entrypoint =====================


def run_review_graph(
    db: Session,
    *,
    task_id: int,
    contract: Contract | None,
    clauses: list[ContractClause],
    prompt_tpl_content: str,
    progress_cb: Callable[[int], None] | None = None,
) -> dict:
    """Build and run the review multi-agent collaboration graph; returns {findings, stats, opinion, tokens}.

    The data contract is identical to the legacy pipeline (findings dict structure / scoring口径 /
    opinion copy slot). review_service.run_review only replaces the core execution segment; the
    report-persistence logic is unchanged.
    """
    trace = TraceRecorder("review", task_id)
    contract_type = contract.contract_type if contract else "other"
    # Extract plain values before concurrency (worker threads must not touch the ORM)
    clause_values = [
        {"clause_id": c.id, "clause_no": c.clause_no, "clause_type": c.clause_type, "content": c.content}
        for c in clauses
    ]
    type_counter: dict[str, int] = {}
    for cl in clause_values:
        type_counter[cl["clause_type"]] = type_counter.get(cl["clause_type"], 0) + 1
    ctx = _Ctx(
        db=db, task_id=task_id, trace=trace, prompt_tpl_content=prompt_tpl_content,
        progress_cb=progress_cb, contract=contract, clauses=clauses, contract_type=contract_type,
    )

    graph = StateGraph(ReviewState)
    graph.add_node("planner", _node_planner(ctx))
    graph.add_node("rule_auditor", _node_rule_auditor(ctx))
    graph.add_node("clause_reviewers", _node_clause_reviewers(ctx))
    graph.add_node("verifier", _node_verifier(ctx))
    graph.add_node("reporter", _node_reporter(ctx))
    graph.add_edge(START, "planner")
    graph.add_edge("planner", "rule_auditor")
    graph.add_edge("rule_auditor", "clause_reviewers")
    graph.add_edge("clause_reviewers", "verifier")
    graph.add_edge("verifier", "reporter")
    graph.add_edge("reporter", END)
    app = graph.compile()

    initial: ReviewState = {
        "contract": {
            "id": contract.id if contract else 0,
            "title": contract.title if contract else "-",
            "amount": contract.amount if contract else 0,
            "clause_types": [f"{k}×{v}" for k, v in type_counter.items()],
        },
        "clauses": clause_values,
    }
    try:
        final = app.invoke(initial, config={"recursion_limit": 40})
        return {
            "findings": final.get("verified_findings") or [],
            "stats": final.get("stats") or {},
            "opinion": final.get("opinion") or "",
            "tokens": trace.total_tokens(),
        }
    finally:
        trace.flush(db)

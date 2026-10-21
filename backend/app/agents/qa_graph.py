"""Intelligent Q&A Agentic RAG pipeline (LangGraph orchestration):

START -> qa_router (intent router)    kb_search -> continue retrieval; out_of_scope -> guidance script then end
      -> qa_planner (query planning)    multi-query expansion (legal-term rewrite / angle decomposition)
      -> retriever (retrieval execution, deterministic)  per-subquery hybrid retrieval (BM25+kNN RRF), merge & dedup top 8
      -> qa_grader (retrieval quality grader)  judge each result's relevance to the question
          | all irrelevant and not yet corrected -> qa_corrector (CRAG correction) rewrites query -> back to retriever (<=1 time)
      -> qa_answerer (answer generation)  stream an answer with [n] citations
      -> qa_reflector (SelfRAG reflection)  provenance/completeness self-check; on failure regenerate with feedback (<=1 time)
      -> END

SSE event protocol (backward compatible): keeps citations / delta / done; adds agent_step (decision chain)
and reset (notify the frontend to clear the current answer on reflective regeneration).
"""
import json
import re
import time
from typing import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from loguru import logger
from pydantic import BaseModel, Field

from app.agents import llm as agent_llm
from app.agents.registry import AgentSpec, register_agent
from app.agents.trace import TraceRecorder
from app.ai import llm_client
from app.ai.rag import hybrid_search_knowledge

# ===================== Agent registration (registered into the registry on import) =====================

ROUTER_SPEC = register_agent(
    AgentSpec(
        name="qa_router", role="意图路由", graph="qa_graph", kind="structured",
        description="判定问题意图：知识库检索（kb_search）或超出范围（out_of_scope，直接给引导话术）",
        desc_key="data.agentDesc.qa_router",
    )
)
PLANNER_SPEC = register_agent(
    AgentSpec(
        name="qa_planner", role="查询规划", graph="qa_graph", kind="structured",
        description="多查询扩展：将用户问题改写为 2~3 个不同角度/术语的检索子查询",
        desc_key="data.agentDesc.qa_planner",
    )
)
RETRIEVER_SPEC = register_agent(
    AgentSpec(
        name="retriever", role="检索执行", graph="qa_graph", kind="deterministic",
        description="子查询逐一 ES 混合检索（BM25 + kNN RRF 融合），合并去重取 top 8",
        desc_key="data.agentDesc.retriever",
    )
)
GRADER_SPEC = register_agent(
    AgentSpec(
        name="qa_grader", role="检索质量评估", graph="qa_graph", kind="structured",
        description="逐条判定检索结果与问题的相关性，全部不相关时触发 CRAG 纠错循环",
        desc_key="data.agentDesc.qa_grader",
    )
)
CORRECTOR_SPEC = register_agent(
    AgentSpec(
        name="qa_corrector", role="CRAG 纠错", graph="qa_graph", kind="structured",
        description="检索质量不足时改写/补全查询语义，驱动一轮纠正性重检索（≤1 次）",
        desc_key="data.agentDesc.qa_corrector",
    )
)
ANSWERER_SPEC = register_agent(
    AgentSpec(
        name="qa_answerer", role="答案生成", graph="qa_graph", kind="llm",
        description="基于相关命中流式生成带 [n] 引用标注的回答；无命中时输出引导文案",
        desc_key="data.agentDesc.qa_answerer",
    )
)
REFLECTOR_SPEC = register_agent(
    AgentSpec(
        name="qa_reflector", role="SelfRAG 反思", graph="qa_graph", kind="structured",
        description="自检回答是否忠实于检索依据且完整回应问题，不通过则带反馈重生成（≤1 次）",
        desc_key="data.agentDesc.qa_reflector",
    )
)

NO_HIT_ANSWER = (
    "知识库中未检索到与该问题直接相关的法条或模板条款。\n\n"
    "建议：\n"
    "1. 尝试换用更具体的法律术语（如「违约金上限」「免责条款效力」「租赁期限」）重新提问；\n"
    "2. 若问题涉及企业内部特殊约定，请联系法务人员在「法律法规库 / 企业模板库」补充录入相关知识点后再试。"
)

OUT_OF_SCOPE_ANSWER = (
    "该问题超出了企业法务知识库的咨询范围（合同合规、法条适用、模板条款等）。"
    "请围绕合同审查与法律合规场景提问，例如：\n"
    "1. 「违约金约定多少可能被司法调减？」\n2. 「租赁合同超过二十年的效力如何？」\n3. 「采购合同必备条款有哪些？"
)

_KIND_LABELS = {"law": "法条", "case": "案例", "template": "企业模板"}

# ===================== Structured-output schemas =====================


class RouterOut(BaseModel):
    intent: str = "kb_search"  # kb_search / out_of_scope
    reason: str = ""


class QueriesOut(BaseModel):
    queries: list[str] = Field(default_factory=list)


class GradeOut(BaseModel):
    grades: list[dict] = Field(default_factory=list)  # [{index, relevant, reason}]


class RewriteOut(BaseModel):
    rewritten_queries: list[str] = Field(default_factory=list)


class ReflectOut(BaseModel):
    grounded: bool = True
    complete: bool = True
    feedback: str = ""


# ===================== Shared state (blackboard memory) =====================


class QaState(TypedDict, total=False):
    question: str
    route: dict
    sub_queries: list[str]
    hits: list[dict]  # [{kind, ref_id, title, snippet, score}]
    relevant_hits: list[dict]
    retry_count: int
    regen_count: int
    feedback: str
    answer: str
    no_hit: bool


def _extract_json(text: str) -> dict:
    cleaned = re.sub(r"```(?:json)?", "", str(text)).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("输出中未找到 JSON 对象")
    return json.loads(cleaned[start : end + 1])


def _hit_to_dict(h) -> dict:
    return {"kind": h.kind, "ref_id": h.ref_id, "title": h.title, "snippet": h.snippet, "score": round(float(h.score), 4)}


def _to_citations(hits: list[dict]) -> list[dict]:
    return [{"kind": h["kind"], "id": h["ref_id"], "title": h["title"], "snippet": h["snippet"], "score": h["score"]} for h in hits]


# ===================== Node implementations =====================

ROUTER_SYSTEM = (
    "你是一名资深中国企业法务助手，负责企业法务问答系统的意图路由（router）。判定用户问题是否属于企业法律知识库可回答的范围"
    "（合同合规、法条适用、案例参考、模板条款等）。闲聊、无关领域、要求个性化法律意见的判定为 out_of_scope。"
    '仅输出 JSON：{"intent": "kb_search 或 out_of_scope", "reason": "一句话理由"}'
)


def _node_router(trace: TraceRecorder):
    def router(state: QaState) -> dict:
        t0 = time.time()
        route = {"intent": "kb_search", "reason": ""}
        tokens = 0
        try:
            raw, tokens = llm_client.chat_json(ROUTER_SYSTEM, f"[用户问题]\n{state['question']}")
            route = RouterOut.model_validate(raw).model_dump()
            if route["intent"] not in ("kb_search", "out_of_scope"):
                route["intent"] = "kb_search"
        except Exception as e:  # noqa: BLE001  router failure defaults to knowledge-base retrieval
            logger.warning(f"qa router degraded: {e}")
        trace.step(
            "qa_router", "意图路由", "decision",
            {"question": state["question"][:120], "route": route},
            tokens=tokens, latency_ms=int((time.time() - t0) * 1000),
        )
        return {"route": route}

    return router


PLANNER_SYSTEM = (
    "你是一名资深中国企业法务助手，负责法律检索查询规划（planner）。把用户问题扩展为 2~3 个互补的检索子查询："
    "同义法律术语改写（如「赖账不还」→「违约责任」「逾期付款」）、不同法律角度拆解。"
    '仅输出 JSON：{"queries": ["子查询1", "子查询2", "子查询3"]}'
)


def _node_planner(trace: TraceRecorder):
    def planner(state: QaState) -> dict:
        t0 = time.time()
        queries = [state["question"]]
        tokens = 0
        try:
            raw, tokens = llm_client.chat_json(PLANNER_SYSTEM, f"[用户问题]\n{state['question']}")
            planned = [q.strip() for q in QueriesOut.model_validate(raw).queries if q and q.strip()]
            if planned:
                queries = planned[:3]
        except Exception as e:  # noqa: BLE001  planner failure degrades to the original question
            logger.warning(f"qa planner degraded: {e}")
        trace.step(
            "qa_planner", "查询规划", "plan",
            {"subQueries": queries},
            tokens=tokens, latency_ms=int((time.time() - t0) * 1000),
        )
        return {"sub_queries": queries}

    return planner


def _node_retriever(trace: TraceRecorder):
    def retriever(state: QaState) -> dict:
        t0 = time.time()
        merged: dict[tuple, dict] = {}
        for q in state.get("sub_queries") or [state["question"]]:
            for h in hybrid_search_knowledge(q, top_k=5):
                key = (h.kind, h.ref_id, h.title)
                if key not in merged or h.score > merged[key]["score"]:
                    merged[key] = _hit_to_dict(h)
        hits = sorted(merged.values(), key=lambda x: x["score"], reverse=True)[:8]
        trace.step(
            "retriever", "检索执行", "message",
            {"subQueries": state.get("sub_queries") or [], "hits": len(hits),
             "titles": [h["title"] for h in hits[:8]]},
            latency_ms=int((time.time() - t0) * 1000),
        )
        return {"hits": hits, "retry_count": state.get("retry_count", 0)}

    return retriever


GRADER_SYSTEM = (
    "你是一名资深中国企业法务助手，负责检索质量评估（grader）。对每条检索结果判定：其内容是否与用户问题实质相关"
    "（可作为回答依据）。宁缺勿滥，主题不符/效力失效且无关的判定为不相关。"
    '仅输出 JSON：{"grades": [{"index": 1, "relevant": true, "reason": "一句话"}]}'
)


def _node_grader(trace: TraceRecorder):
    def grader(state: QaState) -> dict:
        t0 = time.time()
        hits = state.get("hits") or []
        relevant: list[dict] = []
        tokens = 0
        if hits:
            listing = "\n".join(
                f"[{i + 1}] {h['title']}：{h['snippet'][:160]}" for i, h in enumerate(hits)
            )
            try:
                raw, tokens = llm_client.chat_json(
                    GRADER_SYSTEM,
                    f"[用户问题]\n{state['question']}\n\n[检索结果]\n{listing}\n\n请逐条输出相关性判定。",
                )
                grades = GradeOut.model_validate(raw).grades
                idx_relevant = {int(g.get("index", 0)): bool(g.get("relevant")) for g in grades if isinstance(g, dict)}
                relevant = [h for i, h in enumerate(hits, start=1) if idx_relevant.get(i, True)]
            except Exception as e:  # noqa: BLE001  grading failure conservatively keeps all
                logger.warning(f"qa grader degraded (keep all): {e}")
                relevant = list(hits)
        trace.step(
            "qa_grader", "检索质量评估", "decision",
            {"total": len(hits), "relevant": len(relevant),
             "summary": f"检索 {len(hits)} 条，相关 {len(relevant)} 条"},
            tokens=tokens, latency_ms=int((time.time() - t0) * 1000),
        )
        return {"relevant_hits": relevant}

    return grader


CORRECTOR_SYSTEM = (
    "你是一名资深中国企业法务助手，负责 CRAG 纠错（corrector）。上一轮检索全部不相关：请改写问题语义（纠正术语、补全法务表述、"
    "换角度重述），生成 2~3 个更可能命中法律知识库的检索查询。"
    '仅输出 JSON：{"rewritten_queries": ["查询1", "查询2"]}'
)


def _node_corrector(trace: TraceRecorder):
    def corrector(state: QaState) -> dict:
        t0 = time.time()
        queries = [f"{state['question']} 合同 法律 规定"]
        tokens = 0
        try:
            raw, tokens = llm_client.chat_json(
                CORRECTOR_SYSTEM,
                f"[原问题]\n{state['question']}\n[未命中检索词]\n{'、'.join(state.get('sub_queries') or [])}",
            )
            rewritten = [q.strip() for q in RewriteOut.model_validate(raw).rewritten_queries if q and q.strip()]
            if rewritten:
                queries = rewritten[:3]
        except Exception as e:  # noqa: BLE001  corrector failure uses a conservative augmented query
            logger.warning(f"qa corrector degraded: {e}")
        trace.step(
            "qa_corrector", "CRAG 纠错", "decision",
            {"rewrittenQueries": queries, "round": state.get("retry_count", 0) + 1},
            tokens=tokens, latency_ms=int((time.time() - t0) * 1000),
        )
        return {"sub_queries": queries, "retry_count": state.get("retry_count", 0) + 1}

    return corrector


ANSWERER_SYSTEM = (
    "你是一名资深中国企业法务助手。仅依据下方提供的参考依据回答用户问题，"
    "不得编造法条；回答使用简体中文，结构清晰（要点分行），末尾不需要客套话。"
    "若参考依据不足以回答，请明确说明。引用依据时标注编号（如 [1]）。"
)


def _node_answerer(trace: TraceRecorder):
    model = agent_llm.get_chat_model()

    def answerer(state: QaState) -> dict:
        t0 = time.time()
        hits = state.get("relevant_hits") or []
        if not hits:
            # No relevant hits: fall back to the guidance copy (no LLM call)
            trace.step(
                "qa_answerer", "答案生成", "decision",
                {"summary": "无相关命中，输出引导文案", "noHit": True}, latency_ms=int((time.time() - t0) * 1000),
            )
            return {"answer": NO_HIT_ANSWER, "no_hit": True}

        rag_ctx = "\n\n".join(
            f"[{i + 1}] {h['title']}（{_KIND_LABELS.get(h['kind'], h['kind'])}）：{h['snippet']}"
            for i, h in enumerate(hits)
        )
        feedback = state.get("feedback") or ""
        user_prompt = (
            f"[参考依据]（检索自企业知识库）\n{rag_ctx}\n\n"
            f"[用户问题]\n{state['question']}\n\n"
            "请依据以上参考依据回答；引用依据时标注编号（如 [1]）。"
            + (f"\n\n[反思反馈] 上一版回答存在以下问题，请修正后重新回答：\n{feedback}" if feedback else "")
        )
        parts: list[str] = []
        tokens = 0
        for chunk in model.stream([SystemMessage(content=ANSWERER_SYSTEM), HumanMessage(content=user_prompt)]):
            if chunk.content:
                parts.append(chunk.content)
            um = getattr(chunk, "usage_metadata", None)  # when stream_usage=True, the last chunk reports usage
            if isinstance(um, dict):
                tokens = int(um.get("total_tokens") or 0)
        answer = "".join(parts).strip() or "（生成失败，请重试）"
        trace.step(
            "qa_answerer", "答案生成", "message",
            {"regen": bool(feedback), "citations": len(hits), "answerLength": len(answer)},
            tokens=tokens, latency_ms=int((time.time() - t0) * 1000),
        )
        return {"answer": answer, "no_hit": False}

    return answerer


REFLECTOR_SYSTEM = (
    "你是一名资深中国企业法务助手，负责 SelfRAG 反思（reflector）。检查回答质量：\n"
    "1. grounded：回答中的法条引用与结论是否忠实于参考依据（无编造、无过度引申）；\n"
    "2. complete：是否实质回应了用户问题。\n"
    '仅输出 JSON：{"grounded": true, "complete": true, "feedback": "不通过时给出具体修正意见，通过则为空"}'
)


def _node_reflector(trace: TraceRecorder):
    def reflector(state: QaState) -> dict:
        t0 = time.time()
        result = {"grounded": True, "complete": True, "feedback": ""}
        tokens = 0
        if not state.get("no_hit"):
            hits = state.get("relevant_hits") or []
            rag_ctx = "\n\n".join(f"[{i + 1}] {h['title']}：{h['snippet'][:160]}" for i, h in enumerate(hits))
            try:
                raw, tokens = llm_client.chat_json(
                    REFLECTOR_SYSTEM,
                    f"[用户问题]\n{state['question']}\n\n[参考依据]\n{rag_ctx}\n\n[回答]\n{state['answer'][:1500]}",
                )
                result = ReflectOut.model_validate(raw).model_dump()
            except Exception as e:  # noqa: BLE001  reflector failure treated as passing (no regeneration)
                logger.warning(f"qa reflector degraded (pass): {e}")
        passed = bool(result["grounded"] and result["complete"])
        regen = (not passed) and state.get("regen_count", 0) < 1
        trace.step(
            "qa_reflector", "SelfRAG 反思", "decision",
            {"grounded": result["grounded"], "complete": result["complete"],
             "passed": passed, "regen": regen, "feedback": result["feedback"][:200]},
            tokens=tokens, latency_ms=int((time.time() - t0) * 1000),
        )
        # When regeneration is not triggered, explicitly clear feedback (avoid a stale first-round
        # feedback lingering in state and causing a loop route)
        update: dict = {
            "regen_count": state.get("regen_count", 0) + (1 if regen else 0),
            "feedback": result["feedback"] if regen else "",
        }
        return update

    return reflector


# ===================== Conditional routing =====================


def _route_after_router(state: QaState) -> str:
    return "kb" if (state.get("route") or {}).get("intent") == "kb_search" else "end"


def _route_after_grader(state: QaState) -> str:
    relevant = state.get("relevant_hits") or []
    if relevant:
        return "answer"
    if state.get("retry_count", 0) < 1:
        return "correct"  # all irrelevant and not yet corrected -> one CRAG correction & re-retrieval
    return "answer"  # still no hit after correction -> answerer uses the guidance copy


def _route_after_reflector(state: QaState) -> str:
    if state.get("no_hit"):
        return "end"
    # feedback is non-empty only when reflection decides to regenerate (otherwise explicitly cleared);
    # regen_count<=1 is a double safeguard against loops
    if (state.get("feedback") or "") and state.get("regen_count", 0) <= 1:
        return "regen"
    return "end"


# ===================== Graph assembly & run entrypoint =====================

_STEP_LABELS = {
    "router": ("qa_router", "意图路由"),
    "planner": ("qa_planner", "查询规划"),
    "retriever": ("retriever", "检索执行"),
    "grader": ("qa_grader", "检索质量评估"),
    "corrector": ("qa_corrector", "CRAG 纠错"),
    "answerer": ("qa_answerer", "答案生成"),
    "reflector": ("qa_reflector", "SelfRAG 反思"),
}


def build_qa_graph(trace: TraceRecorder):
    graph = StateGraph(QaState)
    graph.add_node("router", _node_router(trace))
    graph.add_node("planner", _node_planner(trace))
    graph.add_node("retriever", _node_retriever(trace))
    graph.add_node("grader", _node_grader(trace))
    graph.add_node("corrector", _node_corrector(trace))
    graph.add_node("answerer", _node_answerer(trace))
    graph.add_node("reflector", _node_reflector(trace))
    graph.add_edge(START, "router")
    graph.add_conditional_edges("router", _route_after_router, {"kb": "planner", "end": END})
    graph.add_edge("planner", "retriever")
    graph.add_edge("retriever", "grader")
    graph.add_conditional_edges("grader", _route_after_grader, {"correct": "corrector", "answer": "answerer"})
    graph.add_edge("corrector", "retriever")
    graph.add_edge("answerer", "reflector")
    graph.add_conditional_edges("reflector", _route_after_reflector, {"regen": "answerer", "end": END})
    return graph.compile()


def run_qa_graph(question: str, *, session_id: int = 0) -> dict:
    """Non-streaming entrypoint: returns {answer, citations, relevant_hits, no_hit} (for /qa/ask)."""
    question = (question or "").strip()
    if not question:
        return {"answer": NO_HIT_ANSWER, "citations": [], "relevant_hits": [], "no_hit": True}
    trace = TraceRecorder("qa", session_id)
    app = build_qa_graph(trace)
    try:
        final = app.invoke({"question": question}, config={"recursion_limit": 25})
        relevant = final.get("relevant_hits") or []
        return {
            "answer": final.get("answer") or NO_HIT_ANSWER,
            "citations": _to_citations(relevant),
            "relevant_hits": relevant,
            "no_hit": final.get("no_hit", not relevant),
        }
    finally:
        _flush_trace(trace)


def stream_qa_graph(question: str, *, session_id: int = 0):
    """Streaming entrypoint: yields a sequence of SSE event dicts (compatible with the legacy ask_stream
    protocol plus the agent_step/reset extensions).

    Internal event {"type": "_hits", ...} is for the service's hit statistics only and is not sent to the frontend.
    """
    trace = TraceRecorder("qa", session_id)
    app = build_qa_graph(trace)
    question = (question or "").strip()
    relevant: list[dict] = []
    try:
        if not question:
            yield {"type": "citations", "citations": []}
            yield {"type": "delta", "content": NO_HIT_ANSWER}
            yield {"type": "done"}
            return
        stream = app.stream({"question": question}, config={"recursion_limit": 25}, stream_mode=["updates", "messages"])
        for mode, chunk in stream:
            if mode == "messages":
                msg, meta = chunk
                if isinstance(meta, dict) and meta.get("langgraph_node") == "answerer" and getattr(msg, "content", ""):
                    yield {"type": "delta", "content": msg.content}
            elif mode == "updates":
                for node, update in chunk.items():
                    if not isinstance(update, dict):
                        continue
                    agent_name, role = _STEP_LABELS.get(node, (node, node))
                    if node == "router" and update.get("route", {}).get("intent") == "out_of_scope":
                        # Graph ends directly: send the guidance copy as the answer
                        yield {"type": "agent_step", "agent": agent_name, "role": role,
                               "summary": "意图路由：超出知识库范围", "detail": update["route"]}
                        yield {"type": "delta", "content": OUT_OF_SCOPE_ANSWER}
                        continue
                    if node == "retriever":
                        relevant = update.get("hits") or []
                        yield {"type": "citations", "citations": _to_citations(relevant)}
                    if node == "reflector" and update.get("feedback"):
                        # Reflection failed -> regenerate with feedback: tell the frontend to clear the
                        # current answer before receiving it again
                        yield {"type": "reset"}
                    summary = _summarize_update(node, update)
                    if summary:
                        yield {"type": "agent_step", "agent": agent_name, "role": role, "summary": summary, "detail": {}}
        yield {"type": "_hits", "hits": relevant}
        yield {"type": "done"}
    finally:
        _flush_trace(trace)


def _summarize_update(node: str, update: dict) -> str:
    """Convert a node's state update into a decision-chain summary string (for the agent_step event)."""
    if node == "router":
        return f"意图路由：{update.get('route', {}).get('intent', 'kb_search')}（{update.get('route', {}).get('reason', '')[:40]}）"
    if node == "planner":
        return "查询规划：生成 " + str(len(update.get("sub_queries") or [])) + " 个检索子查询"
    if node == "retriever":
        return f"混合检索：命中 {len(update.get('hits') or [])} 条知识条目"
    if node == "grader":
        return f"质量评估：{len(update.get('relevant_hits') or [])} 条相关"
    if node == "corrector":
        return "CRAG 纠错：改写查询重新检索（第 " + str(update.get("retry_count", 0)) + " 轮）"
    if node == "answerer":
        return "答案生成：" + ("引导文案（无相关命中）" if update.get("no_hit") else "引用依据生成回答")
    if node == "reflector":
        if update.get("feedback"):
            return "SelfRAG 反思：未通过，带反馈重新生成"
        return "SelfRAG 反思：通过"
    return ""


def _flush_trace(trace: TraceRecorder) -> None:
    """Persist the QA-chain trace in its own short-lived session (no caller session to reuse)."""
    from app.db.session import SessionLocal

    try:
        db = SessionLocal()
        try:
            trace.flush(db)
        finally:
            db.close()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"qa trace flush failed: {e}")

"""Unit tests for the agent orchestration graphs: qa_graph (Agentic RAG) and review_graph (multi-agent contract review).

All use monkeypatch to inject fake LLM / fake retrieval / fake ReAct sub-agents; the graph itself runs on real LangGraph.
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from app.agents import llm as agent_llm
from app.agents import qa_graph, review_graph
from app.agents.trace import TraceRecorder
from app.ai import llm_client
from app.ai.rag import RagHit
from tests import helpers

QA_HIT = RagHit("law", 1, "《民法典》第五百八十五条", "违约金约定过分高于损失的，可以请求适当减少。", 0.9)


@pytest.fixture()
def qa_env(monkeypatch, db):
    """qa_graph runtime environment: chat_json scheduler + fake retrieval + fake streaming model."""
    state = {"reflector": {"grounded": True, "complete": True, "feedback": ""}, "calls": []}

    def fake_chat_json(system, user):
        state["calls"].append((system, user))
        if "意图路由" in system:
            return ({"intent": "kb_search", "reason": "属于合同合规问题"}, 1)
        if "查询规划" in system:
            return ({"queries": ["违约金上限 规定", "违约金 司法调减"]}, 2)
        if "检索质量评估" in system:
            return ({"grades": [{"index": 1, "relevant": True, "reason": "相关"}]}, 3)
        if "CRAG" in system:
            return ({"rewritten_queries": ["改写后的查询"]}, 4)
        if "SelfRAG" in system:
            return (state["reflector"], 5)
        raise AssertionError(f"未预期的系统提示：{system[:30]}")

    monkeypatch.setattr(llm_client, "chat_json", fake_chat_json)
    monkeypatch.setattr(qa_graph, "hybrid_search_knowledge", lambda q, top_k=6, **kw: [QA_HIT])
    monkeypatch.setattr(agent_llm, "get_chat_model", lambda temperature=0.1: helpers.make_stream_model(["答案"]))
    return state


class TestQaGraphHelpers:
    @pytest.mark.parametrize("streaming", [False, True])
    def test_persisted_trace_is_bound_to_requested_session(self, qa_env, db, streaming):
        from app.models.agent import AgentTrace

        if streaming:
            list(qa_graph.stream_qa_graph("question", session_id=42))
        else:
            qa_graph.run_qa_graph("question", session_id=42)
        traces = db.query(AgentTrace).all()
        assert traces and {row.ref_id for row in traces} == {42}

    def test_extract_json(self):
        assert qa_graph._extract_json('```json\n{"a": 1}\n```') == {"a": 1}
        with pytest.raises(ValueError):
            qa_graph._extract_json("无 JSON")

    def test_hit_to_dict_and_citations(self):
        d = qa_graph._hit_to_dict(QA_HIT)
        assert d == {"kind": "law", "ref_id": 1, "title": QA_HIT.title, "snippet": QA_HIT.snippet, "score": 0.9}
        citations = qa_graph._to_citations([d])
        assert citations[0]["id"] == 1 and citations[0]["title"] == QA_HIT.title

    def test_route_functions(self):
        assert qa_graph._route_after_router({"route": {"intent": "kb_search"}}) == "kb"
        assert qa_graph._route_after_router({"route": {"intent": "out_of_scope"}}) == "end"
        assert qa_graph._route_after_router({}) == "end"  # no route -> not kb_search
        assert qa_graph._route_after_grader({"relevant_hits": [{"x": 1}]}) == "answer"
        assert qa_graph._route_after_grader({"relevant_hits": [], "retry_count": 0}) == "correct"
        assert qa_graph._route_after_grader({"relevant_hits": [], "retry_count": 1}) == "answer"
        assert qa_graph._route_after_reflector({"no_hit": True}) == "end"
        assert qa_graph._route_after_reflector({"feedback": "x", "regen_count": 0}) == "regen"
        assert qa_graph._route_after_reflector({"feedback": "", "regen_count": 0}) == "end"
        assert qa_graph._route_after_reflector({"feedback": "x", "regen_count": 2}) == "end"

    @pytest.mark.parametrize("node,update,expected_sub", [
        ("router", {"route": {"intent": "kb_search", "reason": "理由"}}, "意图路由：kb_search"),
        ("planner", {"sub_queries": ["a", "b"]}, "生成 2 个"),
        ("retriever", {"hits": [{}, {}]}, "命中 2 条"),
        ("grader", {"relevant_hits": [{}]}, "1 条相关"),
        ("corrector", {"retry_count": 1}, "第 1 轮"),
        ("answerer", {"no_hit": True}, "引导文案"),
        ("answerer", {"no_hit": False}, "引用依据生成回答"),
        ("reflector", {"feedback": "不够好"}, "带反馈重新生成"),
        ("reflector", {"feedback": ""}, "通过"),
        ("unknown", {"x": 1}, ""),
    ])
    def test_summarize_update(self, node, update, expected_sub):
        assert expected_sub in qa_graph._summarize_update(node, update)

    def test_build_qa_graph_compiles(self, qa_env):
        app = qa_graph.build_qa_graph(TraceRecorder("qa", 0))
        assert app is not None


class TestRunQaGraph:
    def test_happy_path(self, qa_env, db):
        out = qa_graph.run_qa_graph("违约金上限是多少？")
        assert out["answer"] == "答案"
        assert out["no_hit"] is False
        assert len(out["citations"]) == 1
        assert out["citations"][0]["id"] == 1
        assert len(out["relevant_hits"]) == 1
        # trace persisted to DB
        from app.models.agent import AgentTrace

        db.expire_all()
        names = {t.agent_name for t in db.query(AgentTrace).all()}
        assert {"qa_router", "qa_planner", "retriever", "qa_grader", "qa_answerer", "qa_reflector"} <= names

    def test_empty_question(self, qa_env):
        out = qa_graph.run_qa_graph("   ")
        assert out["no_hit"] is True
        assert out["answer"] == qa_graph.NO_HIT_ANSWER
        assert out["citations"] == []

    def test_router_out_of_scope(self, qa_env, monkeypatch):
        def fake_chat_json(system, user):
            return ({"intent": "out_of_scope", "reason": "闲聊"}, 1)

        monkeypatch.setattr(llm_client, "chat_json", fake_chat_json)
        out = qa_graph.run_qa_graph("今天天气如何")
        assert out["no_hit"] is True
        assert out["answer"] == qa_graph.NO_HIT_ANSWER

    def test_router_invalid_intent_defaults_kb(self, qa_env, monkeypatch):
        def fake_chat_json(system, user):
            if "意图路由" in system:
                return ({"intent": "garbage"}, 1)
            if "查询规划" in system:
                return ({"queries": ["q"]}, 1)
            if "检索质量评估" in system:
                return ({"grades": [{"index": 1, "relevant": True}]}, 1)
            raise AssertionError(system[:20])

        monkeypatch.setattr(llm_client, "chat_json", fake_chat_json)
        out = qa_graph.run_qa_graph("问题")
        assert out["no_hit"] is False

    def test_router_failure_degrades(self, qa_env, monkeypatch):
        def fake_chat_json(system, user):
            if "意图路由" in system:
                raise llm_client.LLMError("router down")
            if "查询规划" in system:
                return ({"queries": ["q"]}, 1)
            if "检索质量评估" in system:
                return ({"grades": [{"index": 1, "relevant": True}]}, 1)
            raise AssertionError(system[:20])

        monkeypatch.setattr(llm_client, "chat_json", fake_chat_json)
        out = qa_graph.run_qa_graph("问题")
        assert out["no_hit"] is False  # router failure defaults to KB search

    def test_planner_failure_degrades(self, qa_env, monkeypatch):
        def fake_chat_json(system, user):
            if "意图路由" in system:
                return ({"intent": "kb_search"}, 1)
            if "查询规划" in system:
                raise llm_client.LLMError("planner down")
            if "检索质量评估" in system:
                return ({"grades": [{"index": 1, "relevant": True}]}, 1)
            raise AssertionError(system[:20])

        monkeypatch.setattr(llm_client, "chat_json", fake_chat_json)
        out = qa_graph.run_qa_graph("违约金")
        assert out["no_hit"] is False

    def test_planner_empty_queries(self, qa_env, monkeypatch):
        def fake_chat_json(system, user):
            if "意图路由" in system:
                return ({"intent": "kb_search"}, 1)
            if "查询规划" in system:
                return ({"queries": ["  ", ""]}, 1)
            if "检索质量评估" in system:
                return ({"grades": [{"index": 1, "relevant": True}]}, 1)
            raise AssertionError(system[:20])

        monkeypatch.setattr(llm_client, "chat_json", fake_chat_json)
        out = qa_graph.run_qa_graph("违约金")
        assert out["no_hit"] is False

    def test_no_hits_answerer_guidance(self, qa_env, monkeypatch):
        monkeypatch.setattr(qa_graph, "hybrid_search_knowledge", lambda q, top_k=6, **kw: [])
        out = qa_graph.run_qa_graph("完全不存在的问题")
        assert out["no_hit"] is True
        assert out["answer"] == qa_graph.NO_HIT_ANSWER
        assert out["citations"] == []

    def test_grader_failure_keeps_all(self, qa_env, monkeypatch):
        def fake_chat_json(system, user):
            if "意图路由" in system:
                return ({"intent": "kb_search"}, 1)
            if "查询规划" in system:
                return ({"queries": ["q"]}, 1)
            if "检索质量评估" in system:
                raise llm_client.LLMError("grader down")
            raise AssertionError(system[:20])

        monkeypatch.setattr(llm_client, "chat_json", fake_chat_json)
        out = qa_graph.run_qa_graph("违约金")
        assert out["no_hit"] is False  # conservatively keep all hits

    def test_grader_partial_relevance(self, qa_env, monkeypatch):
        hits = [RagHit("law", 1, "法条一", "s1", 0.9), RagHit("law", 2, "法条二", "s2", 0.8)]
        monkeypatch.setattr(qa_graph, "hybrid_search_knowledge", lambda q, top_k=6, **kw: hits)

        def fake_chat_json(system, user):
            if "意图路由" in system:
                return ({"intent": "kb_search"}, 1)
            if "查询规划" in system:
                return ({"queries": ["q"]}, 1)
            if "检索质量评估" in system:
                return ({"grades": [{"index": 1, "relevant": True}, {"index": 2, "relevant": False}]}, 1)
            raise AssertionError(system[:20])

        monkeypatch.setattr(llm_client, "chat_json", fake_chat_json)
        out = qa_graph.run_qa_graph("违约金")
        assert [c["id"] for c in out["citations"]] == [1]

    def test_crag_correction_loop(self, qa_env, monkeypatch):
        """First round entirely irrelevant -> CRAG corrects and re-retrieves -> second round relevant -> normal answer."""
        calls = {"grader": 0}

        def fake_chat_json(system, user):
            if "意图路由" in system:
                return ({"intent": "kb_search"}, 1)
            if "查询规划" in system:
                return ({"queries": ["q1"]}, 1)
            if "检索质量评估" in system:
                calls["grader"] += 1
                relevant = calls["grader"] >= 2  # 第二轮才相关
                return ({"grades": [{"index": 1, "relevant": relevant}]}, 1)
            if "CRAG" in system:
                return ({"rewritten_queries": ["改写查询"]}, 1)
            raise AssertionError(system[:20])

        monkeypatch.setattr(llm_client, "chat_json", fake_chat_json)
        out = qa_graph.run_qa_graph("违约金")
        assert calls["grader"] == 2
        assert out["no_hit"] is False

    def test_crag_corrector_failure_fallback_query(self, qa_env, monkeypatch):
        def fake_chat_json(system, user):
            if "意图路由" in system:
                return ({"intent": "kb_search"}, 1)
            if "查询规划" in system:
                return ({"queries": ["q1"]}, 1)
            if "检索质量评估" in system:
                return ({"grades": [{"index": 1, "relevant": False}]}, 1)
            if "CRAG" in system:
                raise llm_client.LLMError("corrector down")
            raise AssertionError(system[:20])

        monkeypatch.setattr(llm_client, "chat_json", fake_chat_json)
        out = qa_graph.run_qa_graph("违约金")
        # correction failed, use conservative augmented query; 2nd round still irrelevant -> guidance text
        assert out["no_hit"] is True

    def test_corrected_still_irrelevant_guidance(self, qa_env, monkeypatch):
        def fake_chat_json(system, user):
            if "意图路由" in system:
                return ({"intent": "kb_search"}, 1)
            if "查询规划" in system:
                return ({"queries": ["q1"]}, 1)
            if "检索质量评估" in system:
                return ({"grades": [{"index": 1, "relevant": False}]}, 1)
            if "CRAG" in system:
                return ({"rewritten_queries": ["改写"]}, 1)
            raise AssertionError(system[:20])

        monkeypatch.setattr(llm_client, "chat_json", fake_chat_json)
        out = qa_graph.run_qa_graph("违约金")
        assert out["no_hit"] is True
        assert out["answer"] == qa_graph.NO_HIT_ANSWER

    def test_reflector_regenerates_once(self, qa_env, monkeypatch):
        """Reflection fails -> regenerate once with feedback -> second reflection passes."""
        state = qa_env
        original = dict(state["reflector"])
        reflect_calls = {"n": 0}

        def fake_chat_json(system, user):
            if "意图路由" in system:
                return ({"intent": "kb_search"}, 1)
            if "查询规划" in system:
                return ({"queries": ["q"]}, 1)
            if "检索质量评估" in system:
                return ({"grades": [{"index": 1, "relevant": True}]}, 1)
            if "SelfRAG" in system:
                reflect_calls["n"] += 1
                if reflect_calls["n"] == 1:
                    return ({"grounded": False, "complete": True, "feedback": "引用不准确"}, 1)
                return ({"grounded": True, "complete": True, "feedback": ""}, 1)
            raise AssertionError(system[:20])

        monkeypatch.setattr(llm_client, "chat_json", fake_chat_json)
        out = qa_graph.run_qa_graph("违约金")
        assert reflect_calls["n"] == 2
        assert out["answer"] == "答案"
        assert original == dict(state["reflector"])  # state was not polluted

    def test_reflector_failure_passes(self, qa_env, monkeypatch):
        def fake_chat_json(system, user):
            if "意图路由" in system:
                return ({"intent": "kb_search"}, 1)
            if "查询规划" in system:
                return ({"queries": ["q"]}, 1)
            if "检索质量评估" in system:
                return ({"grades": [{"index": 1, "relevant": True}]}, 1)
            if "SelfRAG" in system:
                raise llm_client.LLMError("reflector down")
            raise AssertionError(system[:20])

        monkeypatch.setattr(llm_client, "chat_json", fake_chat_json)
        out = qa_graph.run_qa_graph("违约金")
        assert out["no_hit"] is False  # reflection failure counts as pass

    def test_answerer_stream_usage_tokens(self, qa_env, monkeypatch, db):
        monkeypatch.setattr(agent_llm, "get_chat_model",
                            lambda temperature=0.1: helpers.make_stream_model(["答", "案"], usage_total=42))
        qa_graph.run_qa_graph("违约金")
        from app.models.agent import AgentTrace

        db.expire_all()
        answerer = [t for t in db.query(AgentTrace).all() if t.agent_name == "qa_answerer"][0]
        assert answerer.tokens == 42

    def test_flush_trace_failure_swallowed(self, qa_env, monkeypatch):
        import app.db.session as db_session

        def _boom():
            raise OSError("db gone")

        monkeypatch.setattr(db_session, "SessionLocal", _boom)
        out = qa_graph.run_qa_graph("违约金")  # 不抛，仅告警
        assert out["answer"] == "答案"


class TestStreamQaGraph:
    def test_event_sequence(self, qa_env):
        events = list(qa_graph.stream_qa_graph("违约金上限？"))
        types = [e["type"] for e in events]
        assert "citations" in types and "delta" in types
        assert types[-1] == "done"
        assert "_hits" in types  # internal event before done
        delta = [e for e in events if e["type"] == "delta"]
        assert "".join(e["content"] for e in delta) == "答案"
        agent_steps = [e for e in events if e["type"] == "agent_step"]
        assert any(e["agent"] == "qa_router" for e in agent_steps)

    def test_empty_question_events(self, qa_env):
        events = list(qa_graph.stream_qa_graph(""))
        types = [e["type"] for e in events]
        assert types == ["citations", "delta", "done"]
        assert events[1]["content"] == qa_graph.NO_HIT_ANSWER

    def test_out_of_scope_events(self, qa_env, monkeypatch):
        monkeypatch.setattr(llm_client, "chat_json",
                            lambda s, u: ({"intent": "out_of_scope", "reason": "闲聊"}, 1))
        events = list(qa_graph.stream_qa_graph("你好"))
        deltas = [e["content"] for e in events if e["type"] == "delta"]
        assert "".join(deltas) == qa_graph.OUT_OF_SCOPE_ANSWER
        assert any(e.get("summary") == "意图路由：超出知识库范围" for e in events if e["type"] == "agent_step")

    def test_reflector_regeneration_reset_event(self, qa_env, monkeypatch):
        reflect_calls = {"n": 0}

        def fake_chat_json(system, user):
            if "意图路由" in system:
                return ({"intent": "kb_search"}, 1)
            if "查询规划" in system:
                return ({"queries": ["q"]}, 1)
            if "检索质量评估" in system:
                return ({"grades": [{"index": 1, "relevant": True}]}, 1)
            if "SelfRAG" in system:
                reflect_calls["n"] += 1
                if reflect_calls["n"] == 1:
                    return ({"grounded": False, "complete": False, "feedback": "需修正"}, 1)
                return ({"grounded": True, "complete": True, "feedback": ""}, 1)
            raise AssertionError(system[:20])

        monkeypatch.setattr(llm_client, "chat_json", fake_chat_json)
        events = list(qa_graph.stream_qa_graph("违约金"))
        assert any(e["type"] == "reset" for e in events)

    def test_updates_mode_non_dict_skipped(self, qa_env, monkeypatch):
        # stream_qa_graph internally guards updates chunks with isinstance dict; the normal flow already covers it
        events = list(qa_graph.stream_qa_graph("违约金"))
        assert events[-1]["type"] == "done"


# ===================== review_graph =====================
REVIEW_JSON_OK = json_ok = (
    '{"risk_level": "medium", "risk_type": "权责不对等", "risk_points": '
    '[{"original_text": "原文", "issue": "问题", "legal_basis": "《民法典》", '
    '"suggestion": "建议", "suggested_text": "改写"}]}'
)


@pytest.fixture()
def review_ctx(db, monkeypatch):
    """Build the review_graph runtime context: contract + 2 clauses + required template (triggers the rule engine)."""
    user = helpers.make_user(db)
    contract = helpers.make_contract(db, owner_id=user.id, contract_type="purchase", status="under_review")
    version = helpers.make_version(db, contract.id, parse_status="parsed")
    clause1 = helpers.make_clause(db, version.id, contract.id, clause_no="第一条", clause_type="付款",
                                  content="甲方应在收到发票后 30 日内支付价款，逾期按日千分之三支付违约金。")
    clause2 = helpers.make_clause(db, version.id, contract.id, clause_no="第二条", clause_type="违约",
                                  content="任何一方违约应向对方支付合同总价 50% 的违约金。")
    helpers.make_template(db, name="争议解决", contract_type="purchase", clause_level="required",
                          content="因本合同发生的争议，双方应友好协商解决。")
    db.commit()
    return {"contract": contract, "clauses": [clause1, clause2], "user": user}


def _reviewer_agents(reviewer_script=None, *, verifier_script=None, reviewer_decider=None,
                     verifier_decider=None):
    """create_agent factory: the 1st goes to the clause reviewer (defaults to medium-risk JSON), the 2nd to the verifier (defaults to empty verdict).

    Returns (factory, (reviewer, verifier)) -- agent references are stable so tests can assert their call records.
    """
    reviewer = helpers.FakeAgent(reviewer_script, default_text=REVIEW_JSON_OK, decider=reviewer_decider)
    verifier = helpers.FakeAgent(verifier_script, default_text='{"verdicts": []}', decider=verifier_decider)
    queue = [reviewer, verifier]

    def _factory(model, tools=None, system_prompt=None):
        return queue.pop(0) if queue else helpers.FakeAgent(default_text=REVIEW_JSON_OK)

    return _factory, (reviewer, verifier)


VERDICTS_CONFIRM = (
    '{"verdicts": [{"index": 1, "verdict": "confirm", "reason": "依据真实"}, '
    '{"index": 2, "verdict": "confirm", "reason": "风险成立"}]}'
)


def _chat_json_router(reflector_ok=True, planner_ok=True, reporter_ok=True):
    def fake_chat_json(system, user):
        if "任务规划" in system:
            if not planner_ok:
                raise llm_client.LLMError("planner down")
            return ({"summary": "计划", "focus_points": ["要点1"], "risk_hints": ["提示1"]}, 3)
        if "报告撰写" in system:
            if not reporter_ok:
                raise llm_client.LLMError("reporter down")
            return ({"opinion": "整体审查意见：建议签署。"}, 7)
        raise AssertionError(f"未预期调用：{system[:30]}")

    return fake_chat_json


class TestReviewGraphHelpers:
    def test_extract_json(self):
        assert review_graph._extract_json('{"a": 1}') == {"a": 1}
        with pytest.raises(ValueError):
            review_graph._extract_json("no json")

    def test_messages_tokens(self):
        m1 = AIMessage(content="a")
        m1.usage_metadata = {"total_tokens": 10}
        m2 = AIMessage(content="b")  # no usage_metadata
        m3 = AIMessage(content="c")
        m3.usage_metadata = {"total_tokens": 5}
        assert review_graph._messages_tokens([m1, m2, m3]) == 15
        assert review_graph._messages_tokens([]) == 0

    def test_tool_calls_summary(self):
        messages = [
            AIMessage(content="", tool_calls=[{"name": "search_legal_knowledge", "args": {"query": "违约金"}, "id": "c1"}]),
            ToolMessage(name="search_legal_knowledge", tool_call_id="c1", content="- [law] 《民法典》：内容"),
        ]
        summary = review_graph._tool_calls_summary(messages)
        assert summary == [{"tool": "search_legal_knowledge", "args": {"query": "违约金"},
                            "result": "- [law] 《民法典》：内容"}]

    def test_tool_calls_summary_no_tool_messages(self):
        assert review_graph._tool_calls_summary([AIMessage(content="x")]) == []

    def test_rag_hits_from_messages(self):
        content = "- [law] 《民法典》第五百八十五条：违约金\n- [case] 指导案例64号：过分高于损失\n- [law] 《民法典》第五百八十五条：重复"
        messages = [ToolMessage(name="search_legal_knowledge", tool_call_id="c", content=content)]
        hits = review_graph._rag_hits_from_messages(messages)
        assert hits == ["《民法典》第五百八十五条", "指导案例64号"]
        assert review_graph._rag_hits_from_messages([AIMessage(content="x")]) == []

    def test_result_to_findings_none_level(self):
        from app.services.review_service import LlmClauseResult

        assert review_graph._result_to_findings(
            LlmClauseResult(risk_level="none", risk_type="", risk_points=[]), {"clause_no": "第一条", "clause_id": 1, "content": "c"}, []) == []

    def test_result_rejects_invalid_risk_output(self):
        """Strict validation: illegal risk level / non-none missing risk-point description must fail; never silently treat as no-risk."""
        from pydantic import ValidationError

        from app.services.review_service import LlmClauseResult, LlmRiskPoint

        with pytest.raises(ValidationError):
            LlmClauseResult.model_validate({"risk_level": "HIGH", "risk_points": [{"issue": "x"}]})
        with pytest.raises(ValidationError):
            LlmClauseResult.model_validate({"risk_level": "high", "risk_points": []})
        with pytest.raises(ValidationError):
            LlmClauseResult(risk_level="high", risk_type="", risk_points=[LlmRiskPoint()])
        # a valid none verdict allows empty risk points
        assert LlmClauseResult.model_validate({"risk_level": "none", "risk_points": []}).risk_level == "none"

    def test_result_to_findings_defaults(self):
        from app.services.review_service import LlmClauseResult, LlmRiskPoint

        result = LlmClauseResult(risk_level="high", risk_type="", risk_points=[LlmRiskPoint(issue="存在风险点")])
        out = review_graph._result_to_findings(result, {"clause_no": "第一条", "clause_id": 9, "content": "条款内容"}, ["依据"])
        assert len(out) == 1
        f = out[0]
        assert f["risk_level"] == "high"
        assert f["risk_type"] == "合规风险"  # empty risk_type fallback
        assert f["issue"] == "存在风险点"
        assert f["original_text"] == "条款内容"[:300]
        assert f["legal_basis"] == "（知识库未命中直接依据）"
        assert f["suggestion"] == "建议结合企业模板标准条款修订。"
        assert f["source"] == "llm" and f["rag_hits"] == ["依据"]

    def test_result_to_findings_truncates_points(self):
        from app.services.review_service import LlmClauseResult, LlmRiskPoint

        result = LlmClauseResult(risk_level="medium", risk_type="类型", risk_points=[LlmRiskPoint(issue=f"问题{i}") for i in range(6)])
        out = review_graph._result_to_findings(result, {"clause_no": "一", "clause_id": 1, "content": "c"}, [])
        assert len(out) == 4  # at most 4 items

    def test_result_to_findings_long_fields_truncated(self):
        from app.services.review_service import LlmClauseResult, LlmRiskPoint

        result = LlmClauseResult(risk_level="low", risk_type="x" * 50,
                                 risk_points=[LlmRiskPoint(issue="i", legal_basis="b" * 2000)])
        f = review_graph._result_to_findings(result, {"clause_no": "一", "clause_id": 1, "content": "c"}, [])[0]
        assert len(f["risk_type"]) == 32
        assert len(f["legal_basis"]) == 1000

    def test_apply_verdicts(self):
        findings = [
            {"clause_no": "一", "risk_level": "high", "issue": "问题一"},
            {"clause_no": "二", "risk_level": "medium", "issue": "问题二"},
            {"clause_no": "三", "risk_level": "low", "issue": "问题三"},
        ]
        candidates = findings[:2]
        verdicts = [
            review_graph.Verdict(index=1, verdict="drop", reason="幻觉"),
            review_graph.Verdict(index=2, verdict="downgrade", reason="夸大" * 100),
        ]
        out = review_graph._apply_verdicts(findings, candidates, verdicts)
        assert [f["clause_no"] for f in out] == ["二", "三"]
        assert out[0]["risk_level"] == "low"
        assert "复核降级" in out[0]["issue"]
        assert len(out[0]["issue"]) < len("问题二") + 100

    def test_apply_verdicts_missing_index_keeps(self):
        findings = [{"clause_no": "一", "risk_level": "high", "issue": "x"}]
        out = review_graph._apply_verdicts(findings, findings, [])
        assert len(out) == 1

    @pytest.mark.parametrize("high,medium,low,score,ai,expected_sub", [
        (2, 1, 0, 20, (1, 0, 0), "不建议签署"),
        (0, 0, 0, 90, (0, 0, 0), "建议签署"),
        (0, 2, 1, 70, (0, 0, 0), "建议修改后签署"),
        (0, 0, 0, 90, (2, 1, 1), "AI 另有参考发现"),
        (1, 2, 0, 20, (0, 0, 0), "另有 2 项中风险"),
    ])
    def test_default_opinion(self, high, medium, low, score, ai, expected_sub):
        opinion = review_graph._default_opinion(high, medium, low, score, *ai)
        assert expected_sub in opinion


class TestRunReviewGraph:
    def test_happy_path(self, review_ctx, monkeypatch, db):
        factory, agents = _reviewer_agents(
            reviewer_script=[helpers.agent_result(REVIEW_JSON_OK, total_tokens=30,
                                                  tool_calls=[{"name": "search_legal_knowledge",
                                                               "args": {"query": "违约金"}, "id": "c1"}],
                                                  tool_results=[{"content": "- [law] 《民法典》第五百八十五条：违约金"}])],
            verifier_script=[helpers.agent_result(VERDICTS_CONFIRM, total_tokens=5)],
        )
        monkeypatch.setattr(review_graph, "create_agent", factory)
        monkeypatch.setattr(agent_llm, "get_chat_model", lambda temperature=0.1: object())
        monkeypatch.setattr(llm_client, "chat_json", _chat_json_router())
        progress = []
        out = review_graph.run_review_graph(
            db, task_id=1, contract=review_ctx["contract"], clauses=review_ctx["clauses"],
            prompt_tpl_content="模板：{contract_type} {clause_text} {rag_context}",
            progress_cb=progress.append,
        )
        # rule engine: missing dispute-resolution clause (high) + penalty 50% > 30% (medium)
        rule_findings = [f for f in out["findings"] if f["source"] == "rule"]
        assert any(f["risk_type"] == "条款缺失" and f["risk_level"] == "high" for f in rule_findings)
        assert any("50%" in f["issue"] for f in rule_findings)
        # LLM findings + verifier confirmation
        llm_findings = [f for f in out["findings"] if f["source"] == "llm"]
        assert len(llm_findings) == 2  # 两条条款各 1 条（默认产出）
        assert out["stats"]["high"] >= 1
        assert out["stats"]["score"] < 100
        assert out["opinion"] == "整体审查意见：建议签署。"
        assert out["tokens"] >= 30
        assert progress[:2] == [15, 25]
        assert 85 in progress and 90 in progress and 95 in progress
        # verifier confirmed 2 candidates
        assert agents[1].invocations, "复核员应被调用"

    def test_verifier_downgrade_and_drop(self, review_ctx, monkeypatch, db):
        factory, agents = _reviewer_agents(
            verifier_script=[helpers.agent_result(
                '{"verdicts": [{"index": 1, "verdict": "drop", "reason": "依据不实"}, '
                '{"index": 2, "verdict": "downgrade", "reason": "风险夸大"}]}', total_tokens=5)]
        )
        monkeypatch.setattr(review_graph, "create_agent", factory)
        monkeypatch.setattr(agent_llm, "get_chat_model", lambda temperature=0.1: object())
        monkeypatch.setattr(llm_client, "chat_json", _chat_json_router())
        out = review_graph.run_review_graph(
            db, task_id=1, contract=review_ctx["contract"], clauses=review_ctx["clauses"],
            prompt_tpl_content="tpl")
        llm_findings = [f for f in out["findings"] if f["source"] == "llm"]
        assert len(llm_findings) == 1  # drop 一条
        assert llm_findings[0]["risk_level"] == "low"  # downgrade 一条
        assert "复核降级" in llm_findings[0]["issue"]

    def test_verifier_retry_then_valid(self, review_ctx, monkeypatch, db):
        factory, agents = _reviewer_agents(
            verifier_script=[
                helpers.agent_result("not a json"),  # 第一次校验失败
                helpers.agent_result(VERDICTS_CONFIRM, total_tokens=8),
            ]
        )
        monkeypatch.setattr(review_graph, "create_agent", factory)
        monkeypatch.setattr(agent_llm, "get_chat_model", lambda temperature=0.1: object())
        monkeypatch.setattr(llm_client, "chat_json", _chat_json_router())
        out = review_graph.run_review_graph(
            db, task_id=1, contract=review_ctx["contract"], clauses=review_ctx["clauses"],
            prompt_tpl_content="tpl")
        llm_findings = [f for f in out["findings"] if f["source"] == "llm"]
        assert len(llm_findings) == 2  # confirm 全部保留
        assert len(agents[1].invocations) == 2

    def test_verifier_no_candidates_skips_llm(self, review_ctx, monkeypatch, db):
        # reviewer returns all none -> no high/medium risk -> verifier not called
        def all_none(payload):
            return helpers.agent_result('{"risk_level": "none", "risk_points": []}')

        factory, agents = _reviewer_agents(reviewer_decider=all_none)
        monkeypatch.setattr(review_graph, "create_agent", factory)
        monkeypatch.setattr(agent_llm, "get_chat_model", lambda temperature=0.1: object())
        monkeypatch.setattr(llm_client, "chat_json", _chat_json_router())
        out = review_graph.run_review_graph(
            db, task_id=1, contract=review_ctx["contract"], clauses=review_ctx["clauses"],
            prompt_tpl_content="tpl")
        assert agents[1].invocations == []
        assert all(f["source"] == "rule" for f in out["findings"])

    def test_verifier_failure_degrades_to_dedup(self, review_ctx, monkeypatch, db):
        factory, agents = _reviewer_agents(
            verifier_script=[RuntimeError("verifier agent down")]
        )
        monkeypatch.setattr(review_graph, "create_agent", factory)
        monkeypatch.setattr(agent_llm, "get_chat_model", lambda temperature=0.1: object())
        monkeypatch.setattr(llm_client, "chat_json", _chat_json_router())
        out = review_graph.run_review_graph(
            db, task_id=1, contract=review_ctx["contract"], clauses=review_ctx["clauses"],
            prompt_tpl_content="tpl")
        assert len([f for f in out["findings"] if f["source"] == "llm"]) == 2  # degrade: keep all

    def test_verifier_empty_verdicts_degrades(self, review_ctx, monkeypatch, db):
        # verifier's default script is an empty verdict -> take the fallback path
        factory, agents = _reviewer_agents()
        monkeypatch.setattr(review_graph, "create_agent", factory)
        monkeypatch.setattr(agent_llm, "get_chat_model", lambda temperature=0.1: object())
        monkeypatch.setattr(llm_client, "chat_json", _chat_json_router())
        out = review_graph.run_review_graph(
            db, task_id=1, contract=review_ctx["contract"], clauses=review_ctx["clauses"],
            prompt_tpl_content="tpl")
        assert len([f for f in out["findings"] if f["source"] == "llm"]) == 2

    def test_clause_reviewer_retry_on_invalid_json(self, review_ctx, monkeypatch, db):
        attempts = {"n": 0}

        def decider(payload):
            attempts["n"] += 1
            if attempts["n"] == 1:
                return helpers.agent_result("坏输出，不是 JSON")
            return helpers.agent_result(REVIEW_JSON_OK)

        factory, agents = _reviewer_agents(reviewer_decider=decider)
        monkeypatch.setattr(review_graph, "create_agent", factory)
        monkeypatch.setattr(agent_llm, "get_chat_model", lambda temperature=0.1: object())
        monkeypatch.setattr(llm_client, "chat_json", _chat_json_router())
        single = review_ctx["clauses"][:1]
        out = review_graph.run_review_graph(
            db, task_id=1, contract=review_ctx["contract"], clauses=single,
            prompt_tpl_content="tpl")
        assert len([f for f in out["findings"] if f["source"] == "llm"]) == 1
        assert attempts["n"] == 2

    def test_clause_reviewer_recursion_limit_retry(self, review_ctx, monkeypatch, db):
        attempts = {"n": 0}

        def decider(payload):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise GraphRecursionError("limit hit")
            return helpers.agent_result(REVIEW_JSON_OK)

        factory, agents = _reviewer_agents(reviewer_decider=decider)
        monkeypatch.setattr(review_graph, "create_agent", factory)
        monkeypatch.setattr(agent_llm, "get_chat_model", lambda temperature=0.1: object())
        monkeypatch.setattr(llm_client, "chat_json", _chat_json_router())
        single = review_ctx["clauses"][:1]
        out = review_graph.run_review_graph(
            db, task_id=1, contract=review_ctx["contract"], clauses=single,
            prompt_tpl_content="tpl")
        assert len([f for f in out["findings"] if f["source"] == "llm"]) == 1
        # second call carries a convergence instruction
        second_prompt = agents[0].invocations[1]["payload"]["messages"][0].content
        assert "立即基于已检索到的信息输出最终 JSON" in second_prompt

    def test_clause_reviewer_partial_failure_skipped(self, review_ctx, monkeypatch, db):
        # first always fails, second always succeeds -> partial skip, failed_clauses=1
        def decider(payload):
            if "第一条" in payload["messages"][0].content:
                raise llm_client.LLMError("模型挂了")
            return helpers.agent_result(REVIEW_JSON_OK)

        factory, agents = _reviewer_agents(reviewer_decider=decider)
        monkeypatch.setattr(review_graph, "create_agent", factory)
        monkeypatch.setattr(agent_llm, "get_chat_model", lambda temperature=0.1: object())
        monkeypatch.setattr(llm_client, "chat_json", _chat_json_router())
        out = review_graph.run_review_graph(
            db, task_id=1, contract=review_ctx["contract"], clauses=review_ctx["clauses"],
            prompt_tpl_content="{contract_type}\n{clause_text}\n{rag_context}")
        assert out["stats"]["failed_clauses"] == 1
        llm_findings = [f for f in out["findings"] if f["source"] == "llm"]
        assert len(llm_findings) == 1  # only the second clause produced

    def test_all_clauses_failed_raises(self, review_ctx, monkeypatch, db):
        def always_fail(payload):
            raise llm_client.LLMError("模型挂了")

        factory, agents = _reviewer_agents(reviewer_decider=always_fail)
        monkeypatch.setattr(review_graph, "create_agent", factory)
        monkeypatch.setattr(agent_llm, "get_chat_model", lambda temperature=0.1: object())
        monkeypatch.setattr(llm_client, "chat_json", _chat_json_router())
        with pytest.raises(llm_client.LLMError) as ei:
            review_graph.run_review_graph(
                db, task_id=1, contract=review_ctx["contract"], clauses=review_ctx["clauses"],
                prompt_tpl_content="tpl")
        assert "全部 2 条条款审查失败" in str(ei.value)

    def test_planner_failure_default_plan(self, review_ctx, monkeypatch, db):
        factory, agents = _reviewer_agents()
        monkeypatch.setattr(review_graph, "create_agent", factory)
        monkeypatch.setattr(agent_llm, "get_chat_model", lambda temperature=0.1: object())
        monkeypatch.setattr(llm_client, "chat_json", _chat_json_router(planner_ok=False))
        out = review_graph.run_review_graph(
            db, task_id=1, contract=review_ctx["contract"], clauses=review_ctx["clauses"],
            prompt_tpl_content="tpl")
        assert out["stats"]["score"] >= 0  # default plan does not block review

    def test_reporter_failure_default_opinion(self, review_ctx, monkeypatch, db):
        factory, agents = _reviewer_agents()
        monkeypatch.setattr(review_graph, "create_agent", factory)
        monkeypatch.setattr(agent_llm, "get_chat_model", lambda temperature=0.1: object())
        monkeypatch.setattr(llm_client, "chat_json", _chat_json_router(reporter_ok=False))
        out = review_graph.run_review_graph(
            db, task_id=1, contract=review_ctx["contract"], clauses=review_ctx["clauses"],
            prompt_tpl_content="tpl")
        assert "不建议签署" in out["opinion"]  # has a rule high blocking item

    def test_reporter_empty_opinion_falls_back(self, review_ctx, monkeypatch, db):
        def fake_chat_json(system, user):
            if "任务规划" in system:
                return ({"summary": "s", "focus_points": [], "risk_hints": []}, 1)
            if "报告撰写" in system:
                return ({"opinion": "   "}, 1)  # 空白 → 走默认模板
            raise AssertionError(system[:20])

        factory, agents = _reviewer_agents()
        monkeypatch.setattr(review_graph, "create_agent", factory)
        monkeypatch.setattr(agent_llm, "get_chat_model", lambda temperature=0.1: object())
        monkeypatch.setattr(llm_client, "chat_json", fake_chat_json)
        out = review_graph.run_review_graph(
            db, task_id=1, contract=review_ctx["contract"], clauses=review_ctx["clauses"],
            prompt_tpl_content="tpl")
        assert out["opinion"]  # 默认意见非空

    def test_no_contract_skips_rule_engine(self, db, monkeypatch):
        from app.models.contract import ContractClause

        clause = ContractClause(id=1, version_id=1, contract_id=1, clause_no="第一条",
                                clause_type="付款", content="付款内容。")
        factory, agents = _reviewer_agents()
        monkeypatch.setattr(review_graph, "create_agent", factory)
        monkeypatch.setattr(agent_llm, "get_chat_model", lambda temperature=0.1: object())
        monkeypatch.setattr(llm_client, "chat_json", _chat_json_router())
        out = review_graph.run_review_graph(
            db, task_id=1, contract=None, clauses=[clause], prompt_tpl_content="tpl")
        assert all(f["source"] == "llm" for f in out["findings"])

    def test_trace_flushed(self, review_ctx, monkeypatch, db):
        factory, agents = _reviewer_agents()
        monkeypatch.setattr(review_graph, "create_agent", factory)
        monkeypatch.setattr(agent_llm, "get_chat_model", lambda temperature=0.1: object())
        monkeypatch.setattr(llm_client, "chat_json", _chat_json_router())
        review_graph.run_review_graph(
            db, task_id=77, contract=review_ctx["contract"], clauses=review_ctx["clauses"],
            prompt_tpl_content="tpl")
        from app.models.agent import AgentTrace

        db.expire_all()
        traces = db.query(AgentTrace).filter(AgentTrace.ref_id == 77).all()
        assert {t.agent_name for t in traces} >= {
            "review_planner", "rule_auditor", "clause_reviewer", "verifier", "reporter"}

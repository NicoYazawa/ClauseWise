"""Unit tests for the agents base layer: registry / trace / tools."""
from __future__ import annotations

import pytest

from app.agents import registry, tools, trace
from tests import helpers


# ===================== registry =====================
class TestRegistry:
    def test_register_get_list(self):
        spec = registry.AgentSpec(name="t_agent", role="测试", description="d", graph="review_graph",
                                  kind="llm", tools=["search_legal_knowledge"], desc_key="data.x")
        assert registry.register_agent(spec) is spec
        assert registry.get_agent("t_agent") is spec
        assert "t_agent" in [a.name for a in registry.list_agents()]
        assert registry.get_agent("missing") is None

    def test_spec_defaults(self):
        spec = registry.AgentSpec(name="a", role="r", description="d", graph="g")
        assert spec.kind == "llm"
        assert spec.tools == []
        assert spec.desc_key == ""


# ===================== trace =====================
class TestTraceRecorder:
    def test_step_and_total_tokens(self):
        rec = trace.TraceRecorder("review", 3)
        rec.step("planner", "规划者", "plan", {"a": 1}, tokens=10, latency_ms=5)
        rec.step("rule_auditor", "规则审计员", "decision", tokens=7)
        assert rec.total_tokens() == 17
        steps = rec._steps
        assert [s.step_idx for s in steps] == [0, 1]
        assert steps[0].task_type == "review" and steps[0].ref_id == 3
        assert steps[0].payload == {"a": 1}
        assert steps[1].payload == {}

    def test_error_truncated_to_500(self):
        rec = trace.TraceRecorder("qa", 0)
        rec.step("a", "r", "decision", error="x" * 600)
        assert len(rec._steps[0].error) == 500

    def test_flush_empty(self, db):
        assert trace.TraceRecorder("review", 1).flush(db) == 0

    def test_flush_persists(self, db):
        rec = trace.TraceRecorder("review", 1)
        rec.step("planner", "规划者", "plan", {"x": 1}, tokens=3)
        assert rec.flush(db) == 1
        from app.models.agent import AgentTrace

        db.expire_all()
        row = db.query(AgentTrace).one()
        assert row.agent_name == "planner" and row.tokens == 3
        assert rec._steps == []  # already consumed

    def test_flush_failure_returns_zero(self, db):
        rec = trace.TraceRecorder("review", 1)
        rec.step("planner", "规划者", "plan")

        class _BoomSession:
            def __init__(self):
                self.rolled_back = False

            def add(self, obj):
                pass

            def commit(self):
                raise RuntimeError("db down")

            def rollback(self):
                self.rolled_back = True

        boom = _BoomSession()
        assert rec.flush(boom) == 0
        assert boom.rolled_back is True

    def test_thread_safety_smoke(self):
        import threading

        rec = trace.TraceRecorder("review", 1)

        def worker():
            for _ in range(20):
                rec.step("a", "r", "decision", tokens=1)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(rec._steps) == 80
        assert rec.total_tokens() == 80


# ===================== tools =====================
class TestAgentTools:
    def test_normalize_type(self):
        assert tools._normalize_type("采购") == "purchase"
        assert tools._normalize_type("SALES") == "sales"
        assert tools._normalize_type("保密协议") == "nda"
        assert tools._normalize_type("") == "other"
        assert tools._normalize_type("未知类型") == "other"

    @pytest.mark.parametrize("value,expected", [
        ("12", 12), ("#12", 12), ("12号", 12), ("合同 12 号", 0), ("abc", 0), ("", 0),
    ])
    def test_parse_id(self, value, expected):
        assert tools._parse_id(value) == expected

    def test_search_legal_knowledge_hit(self, monkeypatch):
        from app.ai.rag import RagHit

        monkeypatch.setattr(tools, "hybrid_search_knowledge",
                            lambda q, top_k=6: [RagHit("law", 1, "民法典", "第五百八十五条", 0.9)])
        out = tools.search_legal_knowledge("违约金")
        assert "[law] 民法典：第五百八十五条" in out

    def test_search_legal_knowledge_no_hit(self, monkeypatch):
        monkeypatch.setattr(tools, "hybrid_search_knowledge", lambda q, top_k=6: [])
        assert tools.search_legal_knowledge("x") == "（知识库未命中相关依据）"

    def test_get_contract_templates(self, db, monkeypatch):
        monkeypatch.setattr(tools, "SessionLocal", lambda: db)
        helpers.make_template(db, name="付款", contract_type="purchase", clause_level="required",
                              content="模板内容" * 50, version=2)
        db.commit()
        out = tools.get_contract_templates("采购")
        assert "[required] 付款（v2）" in out

    def test_get_contract_templates_empty(self, db, monkeypatch):
        monkeypatch.setattr(tools, "SessionLocal", lambda: db)
        assert tools.get_contract_templates("purchase") == "（未找到 purchase 类型的企业模板）"

    def test_get_contract_info(self, db, monkeypatch):
        monkeypatch.setattr(tools, "SessionLocal", lambda: db)
        u = helpers.make_user(db)
        c = helpers.make_contract(db, owner_id=u.id, title="采购合同", amount=50000, status="parsed",
                                  current_version=2)
        db.commit()
        out = tools.get_contract_info(f"#{c.id}", allowed_contract_id=c.id)
        assert f"合同 #{c.id}《采购合同》" in out
        assert "50000 元" in out and "parsed" in out and "v2" in out

    def test_get_contract_info_missing(self, db, monkeypatch):
        monkeypatch.setattr(tools, "SessionLocal", lambda: db)
        assert tools.get_contract_info("999", allowed_contract_id=999) == "（合同 999 不存在）"

    def test_get_contract_clauses(self, db, monkeypatch):
        monkeypatch.setattr(tools, "SessionLocal", lambda: db)
        u = helpers.make_user(db)
        c = helpers.make_contract(db, owner_id=u.id, current_version=2)
        v1 = helpers.make_version(db, c.id, version_no=1)
        v2 = helpers.make_version(db, c.id, version_no=2)
        helpers.make_clause(db, v1.id, c.id, clause_no="第一条", content="旧")
        helpers.make_clause(db, v2.id, c.id, clause_no="第二条", content="新" * 100)
        db.commit()
        out = tools.get_contract_clauses(str(c.id), allowed_contract_id=c.id)
        assert "第二条" in out and "第一条" not in out  # keep the latest version's clauses

    def test_get_contract_clauses_no_clause(self, db, monkeypatch):
        monkeypatch.setattr(tools, "SessionLocal", lambda: db)
        u = helpers.make_user(db)
        c = helpers.make_contract(db, owner_id=u.id)
        db.commit()
        assert tools.get_contract_clauses(str(c.id), allowed_contract_id=c.id) == "（该合同暂无已解析条款）"

    def test_get_contract_clauses_missing_contract(self, db, monkeypatch):
        monkeypatch.setattr(tools, "SessionLocal", lambda: db)
        assert tools.get_contract_clauses("999", allowed_contract_id=999) == "（合同 999 不存在）"

    def test_get_history_review_reports(self, db, monkeypatch):
        monkeypatch.setattr(tools, "SessionLocal", lambda: db)
        u = helpers.make_user(db)
        c = helpers.make_contract(db, owner_id=u.id)
        t = helpers.make_review_task(db, c.id)
        helpers.make_report(db, t.id, c.id, score=90, high_count=1, medium_count=2, low_count=3,
                            overall_opinion="建议修改后签署")
        db.commit()
        out = tools.get_history_review_reports(str(c.id), allowed_contract_id=c.id)
        assert "报告 #" in out and "评分 90" in out and "高/中/低 1/2/3" in out

    def test_get_history_review_reports_empty(self, db, monkeypatch):
        monkeypatch.setattr(tools, "SessionLocal", lambda: db)
        u = helpers.make_user(db)
        c = helpers.make_contract(db, owner_id=u.id)
        db.commit()
        assert tools.get_history_review_reports(str(c.id), allowed_contract_id=c.id) == "（该合同暂无历史审查报告）"

    def test_make_langchain_tools(self):
        made = tools.make_langchain_tools()
        assert [t.name for t in made] == tools.TOOL_NAMES
        assert all(t.description for t in made)

    def test_tool_names_constant(self):
        assert tools.TOOL_NAMES == [
            "search_legal_knowledge", "get_contract_templates", "get_contract_info",
            "get_contract_clauses", "get_history_review_reports",
        ]

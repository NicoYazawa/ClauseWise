"""Security regressions for private QA sessions and bounded contract tools."""
import json

import pytest

from app.agents import tools
from tests import helpers

API = "/api/v1"


@pytest.mark.parametrize("name", ["get_contract_info", "get_contract_clauses", "get_history_review_reports"])
def test_contract_tools_deny_without_server_context(name):
    assert "权限" in getattr(tools, name)("1")


@pytest.mark.parametrize("name", ["get_contract_info", "get_contract_clauses", "get_history_review_reports"])
def test_structured_tools_cannot_escape_bound_contract(name):
    tool = next(t for t in tools.make_langchain_tools(contract_id=1) if t.name == name)
    assert "权限" in tool.invoke({"contract_id": "2"})
    assert "allowed_contract_id" not in tool.args
    unbound = next(t for t in tools.make_langchain_tools() if t.name == name)
    assert "权限" in unbound.invoke({"contract_id": "1"})


def test_bound_clauses_use_current_version_not_last_inserted(db, session_factory, monkeypatch):
    monkeypatch.setattr(tools, "SessionLocal", session_factory)
    user = helpers.make_user(db)
    contract = helpers.make_contract(db, owner_id=user.id, current_version=1)
    current = helpers.make_version(db, contract.id, version_no=1)
    future = helpers.make_version(db, contract.id, version_no=2)
    helpers.make_clause(db, current.id, contract.id, content="CURRENT_ONLY")
    helpers.make_clause(db, future.id, contract.id, content="FUTURE_SECRET")
    db.commit()
    tool = next(t for t in tools.make_langchain_tools(contract_id=contract.id) if t.name == "get_contract_clauses")
    answer = tool.invoke({"contract_id": str(contract.id)})
    assert "CURRENT_ONLY" in answer
    assert "FUTURE_SECRET" not in answer


def test_qa_requests_create_private_sessions_and_reject_foreign_reuse(client, db, monkeypatch, admin_user):
    from app.agents.trace import TraceRecorder

    def run(question, *, session_id=0):
        trace = TraceRecorder("qa", session_id)
        trace.step("qa_router", "router", "plan", {"question": question})
        trace.flush(db)
        return {"answer": "ok", "citations": []}

    monkeypatch.setattr("app.ai.llm_client.ensure_llm_configured", lambda: None)
    monkeypatch.setattr("app.agents.qa_graph.run_qa_graph", run)
    first = helpers.make_user(db, username="first")
    second = helpers.make_user(db, username="second")
    db.commit()
    client.user_state["user_id"] = first.id
    a = client.post(f"{API}/qa/ask", json={"question": "PRIVATE_FIRST"}).json()
    b = client.post(f"{API}/qa/ask", json={"question": "ANOTHER"}).json()
    assert a["sessionId"] > 0 and a["sessionId"] != b["sessionId"]
    assert client.post(f"{API}/qa/ask", json={"question": "continue", "sessionId": a["sessionId"]}).status_code == 200
    client.user_state["user_id"] = second.id
    assert client.post(f"{API}/qa/ask", json={"question": "attack", "sessionId": a["sessionId"]}).status_code == 404
    # cross-user reading of another's session trace must be explicitly rejected (403), not silently return an empty list
    assert client.get(f"{API}/agents/trace", params={"task_type": "qa", "ref_id": a["sessionId"]}).status_code == 403
    assert client.get(f"{API}/agents/trace/recent").json() == []
    client.user_state["user_id"] = first.id
    traces = client.get(f"{API}/agents/trace", params={"task_type": "qa", "ref_id": a["sessionId"]}).json()
    assert traces and traces[0]["sessionId"] == a["sessionId"]
    helpers.make_trace(db, task_type="qa", ref_id=0, payload={"secret": "legacy"})
    db.commit()
    # legacy ref_id=0 traces belong to no visible session: reject reading instead of returning content
    assert client.get(f"{API}/agents/trace", params={"task_type": "qa"}).status_code == 403
    admin_user.id = 999  # distinct identity from the first persisted user (id 1)
    client.user_state["user_id"] = None  # even admins cannot read another user's QA
    assert client.get(f"{API}/agents/trace/recent").json() == []


def test_stream_announces_session_and_rejects_foreign_session_before_stream(client, db, monkeypatch):
    monkeypatch.setattr("app.ai.llm_client.ensure_llm_configured", lambda: None)
    monkeypatch.setattr("app.agents.qa_graph.stream_qa_graph", lambda question, **kwargs: iter([{"type": "done"}]))
    user = helpers.make_user(db)
    other = helpers.make_user(db, username="other")
    db.commit()
    client.user_state["user_id"] = user.id
    response = client.post(f"{API}/qa/ask/stream", json={"question": "q"})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert events[0]["type"] == "session" and events[0]["sessionId"] > 0
    client.user_state["user_id"] = other.id
    assert client.post(f"{API}/qa/ask/stream", json={"question": "q", "sessionId": events[0]["sessionId"]}).status_code == 404


def test_review_traces_follow_contract_visibility(client, db):
    owner = helpers.make_user(db, username="owner")
    stranger = helpers.make_user(db, username="stranger")
    contract = helpers.make_contract(db, owner_id=owner.id)
    task = helpers.make_review_task(db, contract.id)
    helpers.make_trace(db, task_type="review", ref_id=task.id)
    db.commit()
    client.user_state["user_id"] = stranger.id
    assert client.get(f"{API}/agents/trace", params={"task_type": "review", "ref_id": task.id}).status_code == 403
    assert client.get(f"{API}/agents/trace/recent").json() == []
    client.user_state["user_id"] = owner.id
    assert len(client.get(f"{API}/agents/trace", params={"task_type": "review", "ref_id": task.id}).json()) == 1

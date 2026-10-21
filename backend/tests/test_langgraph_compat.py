"""LangGraph / LangChain 1.x runtime compatibility tests.

覆盖项目两条关键链路：
1. ReAct 子代理（create_react_agent / create_agent）的工具调用循环
2. StateGraph 条件边与回环（QA 图的 corrector → retriever 回环）
"""
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict


class _ToolCallingFakeModel(FakeMessagesListChatModel):
    """Fake model that supports bind_tools: returns a tool call first, then the final answer."""

    def bind_tools(self, tools: Any, **kwargs: Any):  # noqa: D102
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: D102
        from langchain_core.outputs import ChatGeneration, ChatResult

        already_called = any(getattr(m, "tool_calls", None) for m in messages)
        if not already_called:
            msg = AIMessage(
                content="",
                tool_calls=[{"name": "echo_tool", "args": {"text": "hi"}, "id": "call_1"}],
            )
        else:
            msg = AIMessage(content='{"ok": true}')
        return ChatResult(generations=[ChatGeneration(message=msg)])


def _echo_tool(text: str) -> str:
    """Echo tool."""
    return f"echo:{text}"


@pytest.mark.parametrize("factory_name", ["langgraph_prebuilt", "langchain_agent"])
def test_react_agent_tool_loop(factory_name: str) -> None:
    """ReAct loop: the model issues a tool call -> tool result is fed back -> the model gives the final answer."""
    model = _ToolCallingFakeModel(responses=[])
    tool = StructuredTool.from_function(func=_echo_tool, name="echo_tool", description="回显工具")

    if factory_name == "langgraph_prebuilt":
        from langgraph.prebuilt import create_react_agent

        agent = create_react_agent(model, tools=[tool], prompt="你是一个助手")
    else:
        from langchain.agents import create_agent

        agent = create_agent(model, tools=[tool], system_prompt="你是一个助手")

    result = agent.invoke({"messages": [HumanMessage(content="调用工具")]}, config={"recursion_limit": 8})
    messages: list[BaseMessage] = result["messages"]

    assert len(messages) >= 3, "应包含 AI 工具调用消息 + ToolMessage + 最终回答"
    tool_msgs = [m for m in messages if m.type == "tool"]
    assert tool_msgs, "工具调用未产生 ToolMessage"
    assert tool_msgs[0].content == "echo:hi"
    assert messages[-1].content == '{"ok": true}'


class _RouteState(TypedDict, total=False):
    retried: int
    answer: str


def test_stategraph_conditional_edge_loop() -> None:
    """StateGraph: conditional edge + loop (mirrors the qa_graph corrector -> retriever loop semantics)."""
    calls: list[str] = []

    def retriever(state: _RouteState) -> dict:
        calls.append("retriever")
        return {"retried": state.get("retried", 0) + 1}

    def corrector(state: _RouteState) -> dict:
        calls.append("corrector")
        return {}

    def answerer(state: _RouteState) -> dict:
        calls.append("answerer")
        return {"answer": "done"}

    def route(state: _RouteState) -> str:
        return "correct" if state.get("retried", 0) <= 1 else "answer"

    graph = StateGraph(_RouteState)
    graph.add_node("retriever", retriever)
    graph.add_node("corrector", corrector)
    graph.add_node("answerer", answerer)
    graph.add_edge(START, "retriever")
    graph.add_conditional_edges("retriever", route, {"correct": "corrector", "answer": "answerer"})
    graph.add_edge("corrector", "retriever")
    graph.add_edge("answerer", END)

    app = graph.compile()
    final = app.invoke({"retried": 0}, config={"recursion_limit": 25})

    assert final["answer"] == "done"
    assert calls.count("retriever") == 2, "应回环一次后转入 answerer"
    assert calls.count("corrector") == 1

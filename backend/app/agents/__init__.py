"""Multi-agent orchestration module (LangGraph):

- registry: the agent registry (role / responsibility / tools / owning graph; registers on import)
- tools: wrap existing service capabilities as LangChain tools (callable by the ReAct tool-call loop)
- review_graph: the 5-role contract-review collaboration graph (planner -> rule auditor -> clause reviewers xN -> verifier -> report writer)
- qa_graph: the Q&A Agentic RAG pipeline (router -> planner -> retriever -> evaluator -> corrector -> generator/reflector)
- trace: agent collaboration tracing (agent_trace table, the frontend timeline data source)
"""

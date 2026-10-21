"""Agent registry: centrally register each collaboration graph's agent roles (name/duty/tools/owning graph).

- review_graph / qa_graph call register_agent at module import time
- GET /api/v1/agents reads this registry directly to expose the agent list
"""
from dataclasses import dataclass, field


@dataclass
class AgentSpec:
    name: str  # globally unique registration name (e.g. review_planner)
    role: str  # display role name (Planner / Clause Reviewer ...)
    description: str  # responsibility description
    graph: str  # owning collaboration graph (review_graph / qa_graph)
    kind: str = "llm"  # llm (tool-call loop) / structured (structured output) / deterministic (deterministic node)
    tools: list[str] = field(default_factory=list)  # bound tool names
    # Frontend i18n key for the responsibility description (e.g. data.agentDesc.qa_router).
    # The frontend renders this key first, falling back to the Chinese description.
    desc_key: str = ""


_REGISTRY: dict[str, AgentSpec] = {}


def register_agent(spec: AgentSpec) -> AgentSpec:
    _REGISTRY[spec.name] = spec
    return spec


def get_agent(name: str) -> AgentSpec | None:
    return _REGISTRY.get(name)


def list_agents() -> list[AgentSpec]:
    return list(_REGISTRY.values())

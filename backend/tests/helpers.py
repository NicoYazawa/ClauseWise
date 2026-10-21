"""Test helpers: fake dependencies (OpenAI client / ES / ReAct agent / streaming model) + ORM data factories."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel  # noqa: F401  (kept for backward compatibility)
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from app.models.agent import AgentTrace
from app.models.contract import Contract, ContractClause, ContractVersion
from app.models.knowledge import (
    AuditLog,
    ContractTemplate,
    LawRegulation,
    ModelVersion,
    Notification,
    PromptTemplate,
)
from app.models.review import ReviewReport, ReviewTask, RiskFinding
from app.models.user import Permission, Role, User
from app.models.workflow import ApprovalRecord, WorkflowDefinition, WorkflowInstance


# ===================== OpenAI-compatible client fakes =====================
def make_chat_response(content: str, *, prompt_tokens: int = 10, completion_tokens: int = 5):
    """Build the return body of chat.completions.create."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


class FakeCompletions:
    """Return items in script order; raise if a script element is an Exception. Records call args."""

    def __init__(self, script: list | None = None, *, default: str = '{"ok": true}'):
        self.script = list(script or [])
        self.default = make_chat_response(default)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.script:
            item = self.script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return self.default


class FakeOpenAIClient:
    def __init__(self, script: list | None = None, *, default: str = '{"ok": true}'):
        self.completions = FakeCompletions(script, default=default)
        self.chat = SimpleNamespace(completions=self.completions)
        self.embedding_calls: list[dict] = []
        self.embeddings = SimpleNamespace(create=self._create_embedding)

    def _create_embedding(self, **kwargs):
        self.embedding_calls.append(kwargs)
        n = len(kwargs.get("input") or [])
        return SimpleNamespace(data=[SimpleNamespace(index=i, embedding=[0.1] * 4) for i in range(n)])


def http_response(status_code: int):
    """Build an httpx.Response (used by openai.APIStatusError)."""
    import httpx

    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    return httpx.Response(status_code=status_code, request=request, json={"error": {"message": "boom"}})


def api_status_error(status_code: int, message: str = "boom"):
    """Build an openai.APIStatusError."""
    from openai import APIStatusError

    return APIStatusError(message, response=http_response(status_code), body=None)


# ===================== Elasticsearch fake =====================
class _FakeIndices:
    def __init__(self, es: FakeES):
        self._es = es

    def exists(self, index: str) -> bool:
        self._es.exists_calls.append(index)
        return index in self._es.existing_indices

    def create(self, index: str, mappings=None, settings=None, **kw):
        self._es.created.append({"index": index, "mappings": mappings, "settings": settings})
        self._es.existing_indices.add(index)
        return {"acknowledged": True}

    def delete(self, index: str):
        self._es.deleted.append(index)
        self._es.existing_indices.discard(index)
        return {"acknowledged": True}

    def analyze(self, body=None):
        if not self._es.ik_available:
            raise RuntimeError("no ik plugin")
        return {"tokens": []}


class FakeES:
    """Recording ES fake: search/get/index/info/ping/indices are all scriptable."""

    def __init__(self, *, search_script: list | None = None, get_map: dict | None = None,
                 existing_indices: set | None = None, ik_available: bool = True, ping_ok: bool = True):
        self.search_script = list(search_script or [])
        self.get_map = dict(get_map or {})
        self.existing_indices = set(existing_indices or set())
        self.ik_available = ik_available
        self.ping_ok = ping_ok
        self.indices = _FakeIndices(self)
        self.search_calls: list[dict] = []
        self.indexed: list[dict] = []
        self.exists_calls: list[str] = []
        self.created: list[dict] = []
        self.deleted: list[str] = []
        self.analyze_calls: list[dict] = []

    def ping(self) -> bool:
        return self.ping_ok

    def info(self) -> dict:
        return {"version": {"number": "9.1.2"}}

    def search(self, index=None, **body):
        self.search_calls.append({"index": index, **body})
        if self.search_script:
            item = self.search_script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return {"hits": {"hits": []}}

    def get(self, index: str, id: str):
        if id not in self.get_map:
            raise KeyError(id)
        return {"_source": self.get_map[id]}

    def index(self, index: str, id=None, document=None, **kw):
        self.indexed.append({"index": index, "id": id, "document": document})
        return {"_id": id, "result": "created"}

    def options(self, **kw):
        return self

    def delete(self, index: str, id: str, **kw):
        self.deleted.append(f"{index}/{id}")
        return {"result": "deleted"}


def es_hit(doc_id: str, source: dict) -> dict:
    return {"_id": doc_id, "_source": source}


# ===================== ReAct agent / streaming-model fakes =====================
class FakeAgent:
    """create_agent stand-in: return {"messages": [...]} from the script or raise; after the script is
    exhausted, return default_text.

    Thread-safe (the clause reviewer consumes the same instance concurrently); default_text gives
    unscripted calls deterministic output.
    """

    def __init__(self, script: list | None = None, *, default_text: str | None = None,
                 decider=None):
        self.script = list(script or [])
        self.default_text = default_text
        self.decider = decider  # persistent decider: delegate on every call (good for routing by clause content)
        self.invocations: list[dict] = []
        self._lock = __import__("threading").Lock()

    def invoke(self, payload, config=None):
        with self._lock:
            self.invocations.append({"payload": payload, "config": config})
            item = self.script.pop(0) if self.script else None
        if item is None and self.decider is not None:
            item = self.decider
        if isinstance(item, Exception):
            raise item
        if callable(item):  # decider: dynamically decide the return/raise based on payload
            return item(payload)
        if item is not None:
            return item
        text = self.default_text or '{"risk_level": "none", "risk_points": []}'
        return {"messages": [HumanMessage(content="q"), AIMessage(content=text)]}


def agent_result(final_text: str, *, tool_calls: list[dict] | None = None,
                 tool_results: list[dict] | None = None, total_tokens: int = 0) -> dict:
    """Build a ReAct sub-agent's full message trace (including tool calls and usage)."""
    messages: list = [HumanMessage(content="审查该条款")]
    for i, tc in enumerate(tool_calls or []):
        messages.append(AIMessage(content="", tool_calls=[tc]))
        messages.append(ToolMessage(
            name=tc["name"], tool_call_id=tc["id"],
            content=(tool_results or [{}])[i].get("content", ""),
        ))
    final = AIMessage(content=final_text)
    if total_tokens:
        final.usage_metadata = {"total_tokens": total_tokens}
    messages.append(final)
    return {"messages": messages}


class ScriptedChatModel(BaseChatModel):
    """Reusable fake ChatModel: _stream re-emits chunks each time (no one-shot iterator issue).

    A real BaseChatModel subclass lets LangGraph's stream_mode="messages" callback chain capture deltas.
    """

    chunks: list[str] = []
    usage_total: int | None = None

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        from langchain_core.outputs import ChatGeneration, ChatResult

        msg = AIMessage(content="".join(self.chunks))
        if self.usage_total is not None:
            msg.usage_metadata = {"total_tokens": self.usage_total}
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        from langchain_core.outputs import ChatGenerationChunk

        usage = None
        if self.usage_total is not None:
            usage = {"input_tokens": self.usage_total - 1, "output_tokens": 1, "total_tokens": self.usage_total}
        for c in self.chunks:
            chunk = AIMessageChunk(content=c)
            if usage is not None:
                chunk.usage_metadata = usage
            yield ChatGenerationChunk(message=chunk)


def make_stream_model(chunks: list[str], *, usage_total: int | None = None):
    """Fake model for the qa_graph answerer."""
    return ScriptedChatModel(chunks=list(chunks), usage_total=usage_total)


# ===================== Generic helpers =====================
def now_minus(minutes: int) -> datetime:
    return datetime.now() - timedelta(minutes=minutes)


# ===================== ORM data factories =====================
def make_user(db, *, username: str = "alice", password_hash: str = "hash", real_name: str = "爱丽丝",
              dept_name: str = "法务部", title: str = "法务专员", phone: str | None = None,
              is_active: bool = True, roles=None, last_login_at=None) -> User:
    u = User(
        username=username, password_hash=password_hash, real_name=real_name, dept_name=dept_name,
        title=title, phone=phone, is_active=is_active, last_login_at=last_login_at,
        created_at=datetime.now(),
    )
    if roles is not None:
        u.roles = roles
    db.add(u)
    db.flush()
    return u


def make_role(db, *, code: str = "legal", name: str = "法务", description: str = "",
              data_scope: str = "self", permissions=None) -> Role:
    r = Role(code=code, name=name, description=description, data_scope=data_scope)
    if permissions is not None:
        r.permissions = permissions
    db.add(r)
    db.flush()
    return r


def make_permission(db, *, code: str, name: str = "", module: str = "") -> Permission:
    p = Permission(code=code, name=name or code, module=module)
    db.add(p)
    db.flush()
    return p


def make_contract(db, *, owner_id: int, contract_no: str | None = None, title: str = "采购合同",
                  contract_type: str = "purchase", status: str = "draft", current_version: int = 1,
                  counterparty_name: str = "乙方公司", amount: int = 100000,
                  counterparty_id_no_enc: str | None = None, counterparty_phone_enc: str | None = None,
                  file_sha256: str | None = None) -> Contract:
    c = Contract(
        contract_no=contract_no or f"HT-2026-{owner_id:04d}{title[:2]}",
        title=title, contract_type=contract_type, owner_id=owner_id, status=status,
        current_version=current_version, counterparty_name=counterparty_name, amount=amount,
        counterparty_id_no_enc=counterparty_id_no_enc, counterparty_phone_enc=counterparty_phone_enc,
        file_sha256=file_sha256, created_at=datetime.now(), updated_at=datetime.now(),
    )
    db.add(c)
    db.flush()
    return c


def make_version(db, contract_id: int, *, version_no: int = 1, file_name: str = "v1.pdf",
                 file_path: str | None = None, parse_status: str = "pending",
                 parent_id: int | None = None, parse_channel: str | None = None,
                 parse_error: str | None = None,
                 created_at: datetime | None = None) -> ContractVersion:
    v = ContractVersion(
        contract_id=contract_id, version_no=version_no, parent_id=parent_id, file_name=file_name,
        file_path=file_path, file_size_kb=10, parse_status=parse_status, parse_channel=parse_channel,
        parse_error=parse_error, created_at=created_at or datetime.now(),
    )
    db.add(v)
    db.flush()
    return v


def make_clause(db, version_id: int, contract_id: int, *, clause_no: str = "第一条",
                clause_type: str = "付款", content: str = "甲方应在收到发票后 30 日内支付全部价款。",
                page_no: int = 1, char_start: int = 0, char_end: int = 0) -> ContractClause:
    c = ContractClause(
        version_id=version_id, contract_id=contract_id, clause_no=clause_no, clause_type=clause_type,
        content=content, page_no=page_no, char_start=char_start, char_end=char_end,
    )
    db.add(c)
    db.flush()
    return c


def make_review_task(db, contract_id: int, *, version_id: int | None = None, task_type: str = "full",
                     clause_no: str | None = None, base_version_no: int | None = None,
                     status: str = "pending", progress: int = 0, task_key: str | None = None,
                     model_version: str = "", prompt_version: str = "", error_msg: str | None = None,
                     created_at: datetime | None = None, completed_at: datetime | None = None,
                     duration_ms: int | None = None, tokens_used: int | None = None) -> ReviewTask:
    t = ReviewTask(
        contract_id=contract_id, version_id=version_id, task_type=task_type, clause_no=clause_no,
        base_version_no=base_version_no, status=status, progress=progress, task_key=task_key,
        model_version=model_version, prompt_version=prompt_version, error_msg=error_msg,
        created_at=created_at or datetime.now(), completed_at=completed_at, duration_ms=duration_ms,
        tokens_used=tokens_used,
    )
    db.add(t)
    db.flush()
    return t


def make_finding(db, task_id: int, *, clause_id: int = 0, clause_no: str = "第一条",
                 risk_level: str = "high", risk_type: str = "权责不对等", issue: str = "风险描述",
                 original_text: str = "原文", legal_basis: str = "《民法典》", suggestion: str = "建议修订",
                 suggested_text: str | None = None, rag_hits: list | None = None,
                 source: str = "rule", status: str = "open") -> RiskFinding:
    f = RiskFinding(
        task_id=task_id, clause_id=clause_id, clause_no=clause_no, risk_level=risk_level,
        risk_type=risk_type, issue=issue, original_text=original_text, legal_basis=legal_basis,
        suggestion=suggestion, suggested_text=suggested_text, rag_hits=rag_hits, source=source,
        status=status, created_at=datetime.now(),
    )
    db.add(f)
    db.flush()
    return f


def make_report(db, task_id: int, contract_id: int, *, score: int = 90, high_count: int = 0,
                medium_count: int = 0, low_count: int = 0, overall_opinion: str = "建议签署",
                report_json: dict | None = None, es_doc_id: str | None = None,
                version_id: int | None = None, content_hash: str | None = None,
                bind: bool = True) -> ReviewReport:
    """By default bind the task's version and content hash (matches run_review's report contract); bind=False simulates a historical unbound report."""
    from app.services.review_service import version_content_hash

    task = db.get(ReviewTask, task_id)
    if bind and task is not None and task.version_id:
        version_id = task.version_id
        content_hash = version_content_hash(db, task.version_id)
    summary = {"failedClauses": 0, "needsReReview": False, "taskType": task.task_type if task else "full"}
    if report_json:
        summary.update(report_json.get("summary") or {})
        js = dict(report_json)
        js["summary"] = summary
    else:
        js = {"summary": summary}
    r = ReviewReport(
        task_id=task_id, contract_id=contract_id, version_id=version_id, content_hash=content_hash,
        score=score, high_count=high_count,
        medium_count=medium_count, low_count=low_count, overall_opinion=overall_opinion,
        report_json=js, es_doc_id=es_doc_id, created_at=datetime.now(),
    )
    db.add(r)
    db.flush()
    return r


def make_template(db, *, name: str = "付款", contract_type: str = "purchase",
                  clause_level: str = "optional", content: str = "模板内容", version: int = 1,
                  vectorized: bool = False, es_doc_id: str | None = None) -> ContractTemplate:
    t = ContractTemplate(
        name=name, contract_type=contract_type, clause_level=clause_level, content=content,
        version=version, vectorized=vectorized, es_doc_id=es_doc_id,
        created_at=datetime.now(), updated_at=datetime.now(),
    )
    db.add(t)
    db.flush()
    return t


def make_law(db, *, doc_type: str = "law", title: str = "民法典", content: str = "合同内容",
             source_ref: str = "", effective_date: date | None = None, expiry_date: date | None = None,
             status: str = "active", vectorized: bool = False, hit_count: int = 0,
             es_doc_id: str | None = None) -> LawRegulation:
    law = LawRegulation(
        doc_type=doc_type, title=title, content=content, source_ref=source_ref,
        effective_date=effective_date, expiry_date=expiry_date, status=status, vectorized=vectorized,
        hit_count=hit_count, es_doc_id=es_doc_id, created_at=datetime.now(),
    )
    db.add(law)
    db.flush()
    return law


def make_prompt(db, *, version: str = "v1.0", scene: str = "条款合规审查", content: str = "模板",
                is_active: bool = True) -> PromptTemplate:
    p = PromptTemplate(version=version, scene=scene, content=content, is_active=is_active,
                       updated_at=datetime.now())
    db.add(p)
    db.flush()
    return p


def make_notification(db, *, user_id: int | None = None, type: str = "review_done",
                      title: str = "通知", content: str = "内容", read: bool = False) -> Notification:
    n = Notification(user_id=user_id, type=type, title=title, content=content, read=read,
                     created_at=datetime.now())
    db.add(n)
    db.flush()
    return n


def make_audit_log(db, *, user_id: int | None = 1, username: str = "alice", action: str = "login",
                   resource_type: str = "会话", resource_id: str = "-",
                   detail: dict | None = None) -> AuditLog:
    log = AuditLog(
        user_id=user_id, username=username, action=action, resource_type=resource_type,
        resource_id=resource_id, detail=detail or {"ip": "1.1.1.1", "ua": "ua", "result": "成功"},
        created_at=datetime.now(),
    )
    db.add(log)
    db.flush()
    return log


def make_trace(db, *, task_type: str = "review", ref_id: int = 1, agent_name: str = "planner",
               role: str = "规划者", step_idx: int = 0, action: str = "plan",
               payload: dict | None = None, tokens: int = 0, latency_ms: int = 1,
               error: str | None = None) -> AgentTrace:
    t = AgentTrace(
        task_type=task_type, ref_id=ref_id, agent_name=agent_name, role=role, step_idx=step_idx,
        action=action, payload=payload or {"k": "v"}, tokens=tokens, latency_ms=latency_ms,
        error=error, created_at=datetime.now(),
    )
    db.add(t)
    db.flush()
    return t


def make_model_version(db, *, model_name: str = "deepseek-chat", model_type: str = "llm",
                       is_default: bool = False, eval_metrics: dict | None = None) -> ModelVersion:
    m = ModelVersion(model_name=model_name, model_type=model_type, is_default=is_default,
                     eval_metrics=eval_metrics, activated_at=datetime.now())
    db.add(m)
    db.flush()
    return m


def make_definition(db, *, name: str = "标准合同审批流", contract_types: list | None = None,
                    graph: dict | None = None, version: int = 1, enabled: bool = True) -> WorkflowDefinition:
    d = WorkflowDefinition(
        name=name, contract_types=contract_types if contract_types is not None else ["purchase"],
        graph=graph, version=version, enabled=enabled, updated_at=datetime.now(),
        created_at=datetime.now(),
    )
    db.add(d)
    db.flush()
    return d


def approval_graph(nodes: list[dict] | None = None, edges: list[dict] | None = None) -> dict:
    """Build a workflow-definition graph (default linear chain start -> n1 -> end)."""
    nodes = nodes if nodes is not None else [
        {"id": "n1", "type": "approval", "name": "部门经理审批", "assignees": ["role:dept_manager"]},
    ]
    edges = edges if edges is not None else [
        {"from": "start", "to": "n1"},
        {"from": "n1", "to": "end"},
    ]
    return {"nodes": nodes, "edges": edges}


def make_instance(db, definition_id: int, contract_id: int, *, definition_name: str = "标准合同审批流",
                  definition_version: int = 1, current_node_id: str = "start",
                  current_node_name: str = "发起", status: str = "running",
                  context_snapshot: dict | None = None, node_state: dict | None = None,
                  starter_id: int = 1, starter_name: str = "管理员",
                  started_at: datetime | None = None) -> WorkflowInstance:
    inst = WorkflowInstance(
        definition_id=definition_id, definition_name=definition_name, definition_version=definition_version,
        contract_id=contract_id, current_node_id=current_node_id, current_node_name=current_node_name,
        status=status, context_snapshot=context_snapshot or {}, node_state=node_state or {},
        starter_id=starter_id, starter_name=starter_name, started_at=started_at or datetime.now(),
    )
    db.add(inst)
    db.flush()
    return inst


def make_approval_record(db, instance_id: int, *, node_id: str = "start", node_name: str = "发起",
                         action: str = "submit", operator_id: int = 1, operator_name: str = "管理员",
                         comment: str = "", created_at: datetime | None = None) -> ApprovalRecord:
    r = ApprovalRecord(
        instance_id=instance_id, node_id=node_id, node_name=node_name, action=action,
        operator_id=operator_id, operator_name=operator_name, comment=comment,
        created_at=created_at or datetime.now(),
    )
    db.add(r)
    db.flush()
    return r

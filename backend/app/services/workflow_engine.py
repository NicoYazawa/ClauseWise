"""Approval workflow engine (design doc 3.3):

- Walk the graph JSON: start -> approval / condition / cc -> end
- Condition nodes: safe evaluation via simpleeval allowlist (risk_level/risk_score/amount/contract_type)
- Sign mode: or / and / sequence; progress records assignment slots and stable user IDs
- CC nodes auto-pass; return revisits approval; unsupported delegation actions are rejected
"""
from datetime import datetime
from functools import wraps
import ast
import re

from app.core.exceptions import AppError
from simpleeval import simple_eval
from sqlalchemy.orm import Session

from app.models.contract import Contract
from app.models.knowledge import Notification
from app.models.user import User
from app.models.workflow import ApprovalRecord, WorkflowDefinition, WorkflowInstance

SAFE_NAMES = {"risk_level", "risk_score", "amount", "contract_type", "high_risk", "risk_total"}
VALID_ACTIONS = {"approve", "reject", "return"}


def get_definition_or_404(db: Session, definition_id: int) -> WorkflowDefinition:
    d = db.get(WorkflowDefinition, definition_id)
    if not d:
        raise AppError("WORKFLOW_DEF_NOT_FOUND", 404, "流程定义不存在")
    return d


def get_instance_or_404(db: Session, instance_id: int) -> WorkflowInstance:
    inst = db.get(WorkflowInstance, instance_id)
    if not inst:
        raise AppError("WORKFLOW_INST_NOT_FOUND", 404, "流程实例不存在")
    return inst


def _invalid_graph(message: str = "流程图无效") -> None:
    raise AppError("WORKFLOW_INVALID_GRAPH", 400, message)


def _atomic(fn):
    @wraps(fn)
    def wrapped(db, *args, **kwargs):
        try:
            return fn(db, *args, **kwargs)
        except Exception:
            db.rollback()
            raise
    return wrapped


def _validate_expression(expression: str) -> None:
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, TypeError):
        _invalid_graph("条件表达式无效")
    allowed = (ast.Expression, ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.Compare,
               ast.Name, ast.Load, ast.Constant, ast.And, ast.Or, ast.Not,
               ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.USub, ast.UAdd,
               ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn)
    for part in ast.walk(tree):
        if not isinstance(part, allowed) or (isinstance(part, ast.Name) and part.id not in SAFE_NAMES):
            _invalid_graph("条件表达式包含不支持的操作")


def _nodes_edges(defn: WorkflowDefinition) -> tuple[dict[str, dict], dict[str, str]]:
    graph = defn.graph or {}
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("edges"), list):
        _invalid_graph()
    nodes = {}
    for node in graph["nodes"]:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"] or node["id"] in nodes:
            _invalid_graph()
        nid, kind = node["id"], node.get("type")
        if kind not in {"start", "end", "approval", "condition", "cc"}:
            _invalid_graph("不支持的节点类型")
        if (nid in {"start", "end"} and kind != nid) or (kind in {"start", "end"} and kind != nid):
            _invalid_graph("开始和结束节点 ID 为保留值")
        if kind in {"approval", "cc"}:
            assignments = node.get("assignees")
            if not isinstance(assignments, list) or not assignments or any(
                not isinstance(a, str) or not re.fullmatch(r"(?:role|user):[A-Za-z0-9_@.\-]+", a) for a in assignments
            ) or len(assignments) != len(set(assignments)):
                _invalid_graph("节点必须指定有效且不重复的处理人")
        if kind == "approval" and node.get("signMode", node.get("sign_mode", "or")) not in {"or", "and", "sequence"}:
            _invalid_graph("不支持的会签模式")
        if kind == "condition":
            rules = node.get("rules")
            if (not isinstance(rules, list) or not rules or not isinstance(rules[-1], dict)
                    or rules[-1].get("when") != "default"):
                _invalid_graph("条件节点必须具有默认分支")
            for index, rule in enumerate(rules):
                if not isinstance(rule, dict) or not isinstance(rule.get("goto"), str):
                    _invalid_graph()
                if rule.get("when") == "default":
                    if index != len(rules) - 1:
                        _invalid_graph()
                else:
                    _validate_expression(rule.get("when"))
        nodes[nid] = node
    # Older persisted definitions omit the fixed terminal nodes.
    nodes.setdefault("start", {"id": "start", "type": "start", "name": "发起"})
    nodes.setdefault("end", {"id": "end", "type": "end", "name": "通过签署"})
    edges = {}
    for edge in graph["edges"]:
        if not isinstance(edge, dict):
            _invalid_graph()
        source, target = edge.get("from"), edge.get("to")
        if (not isinstance(source, str) or not isinstance(target, str)
                or source not in nodes or target not in nodes or source in edges
                or source == "end" or target == "start"):
            _invalid_graph("流程连线无效")
        edges[source] = target
    for nid, node in nodes.items():
        if node["type"] not in {"condition", "end"} and nid not in edges:
            _invalid_graph("节点缺少后续连线")
    visited, active = set(), set()
    def visit(nid):
        if nid in active:
            _invalid_graph("流程图存在循环")
        if nid in visited:
            return
        if nid not in nodes:
            _invalid_graph("流程指向不存在的节点")
        active.add(nid)
        node = nodes[nid]
        targets = [r["goto"] for r in node["rules"]] if node["type"] == "condition" else ([edges[nid]] if nid in edges else [])
        for target in targets:
            if target == "start":
                _invalid_graph()
            visit(target)
        active.remove(nid)
        visited.add(nid)
    for nid in nodes:
        visit(nid)
    return nodes, edges


def _next_node(nodes: dict[str, dict], edges: dict[str, str], node_id: str, context: dict) -> tuple[str, dict]:
    current, seen = node_id, set()
    while current not in seen:
        seen.add(current)
        node = nodes.get(current)
        if node is None:
            _invalid_graph("流程指向不存在的节点")
        if node.get("type") == "condition":
            current = _eval_condition(node, context)
            continue
        return current, node
    _invalid_graph("流程图存在循环")


def _eval_condition(node: dict, context: dict) -> str:
    for rule in node.get("rules", []):
        when = rule.get("when", "")
        if when == "default":
            return rule["goto"]
        _validate_expression(when)
        try:
            matched = simple_eval(when, names={k: v for k, v in context.items() if k in SAFE_NAMES}, functions={})
        except Exception as exc:
            raise AppError("WORKFLOW_INVALID_GRAPH", 400, "条件表达式无法计算") from exc
        if matched:
            return rule["goto"]
    _invalid_graph("条件节点没有匹配分支")


def _eval_context(inst: WorkflowInstance) -> dict:
    """Eval context: reconciles the snapshot's score/highRisk with the rule-expression risk_score/high_risk names (SAFE_NAMES allowlist)."""
    snap = dict(inst.context_snapshot or {})
    score = int(snap.get("score", snap.get("risk_score", 0)) or 0)
    high_risk = int(snap.get("highRisk", snap.get("high_risk", 0)) or 0)
    return {
        "score": score,
        "risk_score": score,
        "amount": int(snap.get("amount", 0) or 0),
        "high_risk": high_risk,
        "risk_total": int(snap.get("riskTotal", snap.get("risk_total", 0)) or 0),
        "contract_type": str(snap.get("contract_type", "") or ""),
        "risk_level": "high" if high_risk > 0 else "none",
    }


def _trace_condition(db: Session, inst: WorkflowInstance, node: dict, chosen: str, nodes: dict[str, dict]) -> None:
    """Trace the matched condition into approval_record (consistent with the actual routing)."""
    rule_desc = next(
        (str(r.get("when", "")) for r in node.get("rules", []) if r.get("goto") == chosen),
        "default",
    )
    db.add(
        ApprovalRecord(
            instance_id=inst.id,
            node_id=node.get("id", ""),
            node_name=node.get("name", "条件判断"),
            action="approve",
            operator_id=0,
            operator_name="系统",
            comment=f"规则命中：{rule_desc} → 流转至「{nodes.get(chosen, {}).get('name', chosen)}」节点。",
            created_at=datetime.now(),
        )
    )


def _advance_from(db: Session, inst: WorkflowInstance, defn: WorkflowDefinition, from_node_id: str) -> None:
    """Advance from from_node to the next real stopping node: condition nodes branch by rule eval (goto), cc nodes auto-run without blocking."""
    nodes, edges = _nodes_edges(defn)
    context = _eval_context(inst)

    current = edges.get(from_node_id)
    seen = set()
    while current not in seen:
        seen.add(current)
        if current not in nodes:
            _invalid_graph("流程节点或连线不存在")
        node = nodes[current]
        ntype = node["type"]
        if ntype == "end":
            _finish(inst, "approved", node.get("name", "通过签署"), db)
            return
        if ntype == "condition":
            chosen = _eval_condition(node, context)
            _trace_condition(db, inst, node, chosen, nodes)
            current = chosen  # Enter the chosen node itself, not its outgoing edge.
            continue
        if ntype == "cc":
            db.add(ApprovalRecord(instance_id=inst.id, node_id=current,
                node_name=node.get("name", "抄送"), action="approve", operator_id=0,
                operator_name="系统", comment=f"已抄送：{'、'.join(node['assignees'])}", created_at=datetime.now()))
            current = edges.get(current)
            continue
        if ntype != "approval":
            _invalid_graph()
        inst.current_node_id = current
        inst.current_node_name = node.get("name", "")
        return
    _invalid_graph("流程图存在循环")


def _finish(inst: WorkflowInstance, status: str, node_name: str, db: Session) -> None:
    inst.status = status
    inst.current_node_id = "end"
    inst.current_node_name = node_name if status == "approved" else ("已否决" if status == "rejected" else node_name)
    inst.finished_at = datetime.now()
    contract = db.get(Contract, inst.contract_id)
    if contract:
        contract.status = "approved" if status == "approved" else "rejected"
        contract.updated_at = datetime.now()


def _matches_assignment(assignment: str, operator: User) -> bool:
    kind, value = assignment.split(":", 1)
    return (kind == "role" and value in {r.code for r in operator.roles}) or (
        kind == "user" and value in {operator.username, str(operator.id)})


def _apply_sign_progress(db: Session, inst: WorkflowInstance, defn: WorkflowDefinition, node: dict, operator: User) -> bool:
    assignments = node.get("assignees") or []
    if not assignments:
        _invalid_graph("审批节点没有处理人")
    sign_mode = node.get("signMode", node.get("sign_mode", "or"))
    state = dict(inst.node_state or {})
    progress = dict(state.get(inst.current_node_id, {}))
    done = list(progress.get("done", []))
    slots = dict(progress.get("slots", {}))
    if operator.id in done:
        raise AppError("WORKFLOW_DUPLICATE_APPROVAL", 409, "您已审批过当前节点")
    available = [a for a in assignments if a not in slots]
    if sign_mode == "sequence":
        available = available[:1]
    matching = [a for a in available if _matches_assignment(a, operator)]
    if not matching and not (sign_mode == "or" and "admin" in {r.code for r in operator.roles}):
        raise AppError("WORKFLOW_SIGN_SLOT_REQUIRED", 403, "您不是当前待审批席位的处理人")
    done.append(operator.id)
    slots[matching[0] if matching else assignments[0]] = operator.id
    complete = sign_mode == "or" or len(slots) == len(assignments)
    state[inst.current_node_id] = {"done": done, "slots": slots, "completed": complete}
    inst.node_state = state
    return complete


@_atomic
def start_instance(
    db: Session, defn: WorkflowDefinition, contract: Contract, starter_id: int, starter_name: str, snapshot: dict
) -> WorkflowInstance:
    if not defn.enabled:
        raise AppError("WORKFLOW_DEF_DISABLED", 400, "该流程定义已停用")
    nodes, edges = _nodes_edges(defn)
    inst = WorkflowInstance(
        definition_id=defn.id,
        definition_name=defn.name,
        definition_version=defn.version,
        contract_id=contract.id,
        current_node_id="start",
        current_node_name="发起",
        status="running",
        context_snapshot=snapshot,
        node_state={},
        starter_id=starter_id,
        starter_name=starter_name,
        started_at=datetime.now(),
    )
    db.add(inst)
    db.flush()
    db.add(
        ApprovalRecord(
            instance_id=inst.id,
            node_id="start",
            node_name="发起",
            action="submit",
            operator_id=starter_id,
            operator_name=starter_name,
            comment=(
                f"AI 审查完成：评分 {snapshot.get('score', 0)} 分，高风险 {snapshot.get('highRisk', 0)} 项，"
                f"共 {snapshot.get('riskTotal', 0)} 项风险发现，申请审批。"
            ),
            created_at=datetime.now(),
        )
    )
    # advance from start to the first approval node
    _advance_from(db, inst, defn, "start")
    if inst.status == "running":
        contract.status = "in_approval"
        contract.updated_at = datetime.now()
    db.commit()
    db.refresh(inst)
    return inst


def _can_handle(node: dict, operator: User) -> bool:
    """Approval assignee check; missing assignments never grant access."""
    assignees = node.get("assignees") or []
    if not assignees:
        return False
    roles = {r.code for r in operator.roles}
    if "admin" in roles:
        return True
    for a in assignees:
        if _matches_assignment(a, operator):
            return True
    return False


@_atomic
def act(db: Session, inst: WorkflowInstance, *, action: str, operator: User,
        comment: str, expected_node_id: str | None = None) -> WorkflowInstance:
    inst = db.query(WorkflowInstance).filter(WorkflowInstance.id == inst.id).populate_existing().with_for_update().one()
    if expected_node_id is not None and inst.current_node_id != expected_node_id:
        raise AppError("WORKFLOW_STALE_NODE", 409, "审批节点已变化，请刷新后重试")
    if inst.status != "running":
        raise AppError("WORKFLOW_FINISHED", 400, "该流程已结束，无法操作")
    if action not in VALID_ACTIONS:
        raise AppError("WORKFLOW_INVALID_ACTION", 400, f"非法审批动作：{action}")
    defn = db.get(WorkflowDefinition, inst.definition_id)
    if not defn:
        raise AppError("WORKFLOW_DEF_NOT_FOUND", 404, "流程定义不存在")
    nodes, _ = _nodes_edges(defn)
    current_node = nodes.get(inst.current_node_id, {})
    if current_node.get("type") != "approval":
        _invalid_graph("当前节点不是审批节点")
    # assignee check (RBAC: only users matching the node's assignees by role/user or admin may act)
    if not _can_handle(current_node, operator):
        raise AppError("WORKFLOW_NOT_ASSIGNEE", 403, f"您不是节点「{inst.current_node_name}」的处理人，无法执行该操作")
    completed = False
    if action == "approve":
        completed = _apply_sign_progress(db, inst, defn, current_node, operator)

    operator_id = operator.id
    operator_name = operator.real_name or operator.username
    db.add(
        ApprovalRecord(
            instance_id=inst.id,
            node_id=inst.current_node_id,
            node_name=inst.current_node_name,
            action=action,
            operator_id=operator_id,
            operator_name=operator_name,
            comment=comment,
            created_at=datetime.now(),
        )
    )

    if action == "approve":
        if completed:
            _advance_from(db, inst, defn, inst.current_node_id)
    elif action == "reject":
        _finish(inst, "rejected", "已否决", db)
    elif action == "return":
        # return to the previous approval node (trace back via approval records); countersign progress is voided and re-counted on return
        history = (
            db.query(ApprovalRecord)
            .filter(
                ApprovalRecord.instance_id == inst.id,
                ApprovalRecord.action == "approve",
                ApprovalRecord.node_id != inst.current_node_id,
            )
            .order_by(ApprovalRecord.id.desc())
            .all()
        )
        target = None
        for record in history:  # skip system traces of condition/cc nodes
            node = nodes.get(record.node_id)
            if node and node.get("type") == "approval":
                target = node
                break
        if target is None:
            # fail closed: no guessing a fallback node when the current one is the first approval
            raise AppError("WORKFLOW_NO_PREV_APPROVAL", 400, "当前已是首个审批节点，无法退回上一节点")
        state = dict(inst.node_state or {})
        state.pop(inst.current_node_id, None)
        inst.current_node_id = target["id"]
        inst.current_node_name = target.get("name", "")
        state.pop(inst.current_node_id, None)
        inst.node_state = state
    db.commit()
    db.refresh(inst)
    return inst


def withdraw(db: Session, inst: WorkflowInstance, reason: str) -> WorkflowInstance:
    if inst.status != "running":
        raise AppError("WORKFLOW_FINISHED_WITHDRAW", 400, "该流程已结束，无法撤回")
    db.add(
        ApprovalRecord(
            instance_id=inst.id,
            node_id="start",
            node_name="发起",
            action="withdraw",
            operator_id=inst.starter_id,
            operator_name=inst.starter_name,
            comment=reason,
            created_at=datetime.now(),
        )
    )
    inst.status = "withdrawn"
    inst.finished_at = datetime.now()
    contract = db.get(Contract, inst.contract_id)
    if contract:
        contract.status = "review_passed"
        contract.updated_at = datetime.now()
    db.commit()
    db.refresh(inst)
    return inst


def urge(db: Session, inst: WorkflowInstance, operator_name: str, username: str = "-") -> WorkflowInstance:
    if inst.status != "running":
        raise AppError("WORKFLOW_FINISHED_URGE", 400, "该流程已结束，无需催办")
    db.add(
        ApprovalRecord(
            instance_id=inst.id,
            node_id=inst.current_node_id,
            node_name=inst.current_node_name,
            action="urge",
            operator_id=0,
            operator_name=operator_name,
            comment="发起催办：已向当前节点处理人发送站内信与邮件提醒。",
            created_at=datetime.now(),
        )
    )
    db.add(
        Notification(
            type="approval_todo",
            # urge target is a role group, can't target a single user; keep it visible to all
            title="审批催办提醒",
            content=f"流程实例 #{inst.id}（合同 #{inst.contract_id}）在节点「{inst.current_node_name}」被 {operator_name} 催办，请尽快处理。",
            created_at=datetime.now(),
        )
    )
    db.commit()
    db.refresh(inst)
    return inst


def scan_timeout(db: Session) -> int:
    """Timeout scan (Beat / built-in timer): a node entered > timeout_hours ago and still pending -> urge notification. Returns the scan count."""
    now = datetime.now()
    running = db.query(WorkflowInstance).filter(WorkflowInstance.status == "running").all()
    count = 0
    for inst in running:
        defn = db.get(WorkflowDefinition, inst.definition_id)
        if not defn:
            continue
        nodes, _ = _nodes_edges(defn)
        node = nodes.get(inst.current_node_id, {})
        timeout_hours = node.get("timeoutHours") or node.get("timeout_hours")
        if not timeout_hours:
            continue
        # node's last entry time = its most recent record; fall back to started_at when none
        last = (
            db.query(ApprovalRecord)
            .filter(ApprovalRecord.instance_id == inst.id, ApprovalRecord.node_id == inst.current_node_id)
            .order_by(ApprovalRecord.id.desc())
            .first()
        )
        anchor = last.created_at if last else inst.started_at
        if anchor and (now - anchor).total_seconds() > float(timeout_hours) * 3600:
            db.add(
                Notification(
                    type="approval_timeout",
                    user_id=inst.starter_id,  # targeted reminder to the initiator to chase approval
                    title="审批超时催办",
                    content=(
                        f"流程 #{inst.id} 在节点「{inst.current_node_name}」停留已超过 {timeout_hours} 小时（限时 {timeout_hours} 小时），已自动发送催办提醒。"
                    ),
                    created_at=now,
                )
            )
            count += 1
    if count:
        db.commit()
    return count


def pick_definition_for_contract(db: Session, contract: Contract) -> WorkflowDefinition | None:
    """Pick an enabled workflow definition by contract type (exact match first, else all-type)."""
    defns = db.query(WorkflowDefinition).filter(WorkflowDefinition.enabled == 1).all()  # type: ignore[arg-type]
    exact = [d for d in defns if contract.contract_type in (d.contract_types or [])]
    pool = exact or [d for d in defns if not d.contract_types or len(d.contract_types) >= 6]
    if not pool:
        pool = defns
    return pool[0] if pool else None


def build_definition_out(d: WorkflowDefinition) -> dict:
    graph = d.graph or {}
    return {
        "id": d.id,
        "name": d.name,
        "contractTypes": d.contract_types or [],
        "nodes": graph.get("nodes", []),
        "edges": graph.get("edges", []),
        "version": d.version,
        "enabled": bool(d.enabled),
        "updatedAt": d.updated_at.strftime("%Y-%m-%dT%H:%M:%S") if d.updated_at else None,
    }


def build_instance_out(inst: WorkflowInstance, contract: Contract | None) -> dict:
    return {
        "id": inst.id,
        "definitionId": inst.definition_id,
        "definitionName": inst.definition_name,
        "definitionVersion": inst.definition_version,
        "contractId": inst.contract_id,
        "contractTitle": contract.title if contract else "",
        "currentNodeId": inst.current_node_id,
        "currentNodeName": inst.current_node_name,
        "status": inst.status,
        "contextSnapshot": dict(inst.context_snapshot or {}),
        "starterName": inst.starter_name,
        "startedAt": inst.started_at.strftime("%Y-%m-%dT%H:%M:%S") if inst.started_at else None,
        "finishedAt": inst.finished_at.strftime("%Y-%m-%dT%H:%M:%S") if inst.finished_at else None,
        "records": [
            {
                "id": r.id,
                "instanceId": r.instance_id,
                "nodeId": r.node_id,
                "nodeName": r.node_name,
                "action": r.action,
                "operatorName": r.operator_name,
                "comment": r.comment,
                "createdAt": r.created_at.strftime("%Y-%m-%dT%H:%M:%S") if r.created_at else None,
            }
            for r in inst.records
        ],
    }

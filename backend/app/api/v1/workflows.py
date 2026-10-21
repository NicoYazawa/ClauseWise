"""Approval workflow endpoints (design doc 3.3.1): definitions / instances / approval actions / withdraw / urge."""
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from app.core.exceptions import AppError
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.request_ctx import client_info as _client_info
from app.core.security import get_current_user, require_perm
from app.core.access import get_contract_for_user, visible_contract_ids
from app.db.session import get_db
from app.models.contract import Contract
from app.models.user import User
from app.models.workflow import WorkflowDefinition, WorkflowInstance
from app.schemas.workflow import (
    ActionRequest,
    SaveDefinitionRequest,
    StartApprovalRequest,
    WithdrawRequest,
)
from app.services import approval_gate, workflow_engine

router = APIRouter(prefix="/workflow", tags=["Approval Workflow"])


def _inst_out(db: Session, inst: WorkflowInstance) -> dict:
    contract = db.get(Contract, inst.contract_id)
    return workflow_engine.build_instance_out(inst, contract)


@router.get("/instances")
def fetch_instances(db: Annotated[Session, Depends(get_db)], operator: Annotated[User, Depends(get_current_user)]):
    items = db.query(WorkflowInstance).filter(WorkflowInstance.contract_id.in_(visible_contract_ids(operator))).order_by(WorkflowInstance.id.desc()).all()
    return [_inst_out(db, i) for i in items]


@router.get("/instances/{instance_id}")
def fetch_instance(
    instance_id: int, db: Annotated[Session, Depends(get_db)], operator: Annotated[User, Depends(get_current_user)]
):
    inst = workflow_engine.get_instance_or_404(db, instance_id)
    get_contract_for_user(db, operator, inst.contract_id)
    return _inst_out(db, inst)


@router.post("/instances")
def start_approval(
    payload: StartApprovalRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    operator: Annotated[User, Depends(require_perm("workflow:start"))],
):
    ip, ua = _client_info(request)
    contract = get_contract_for_user(db, operator, payload.contract_id)
    if contract.status not in ("review_passed", "in_approval"):
        raise AppError("WORKFLOW_CONTRACT_NOT_READY", 400, f"合同状态 {contract.status} 不可发起审批（需审查通过且评分 ≥ 85、无高风险）")
    running = (
        db.query(WorkflowInstance.id)
        .filter(WorkflowInstance.contract_id == contract.id, WorkflowInstance.status == "running")
        .first()
    )
    if running:
        raise AppError("WORKFLOW_ALREADY_RUNNING", 409, "该合同已有进行中的审批流程，不能重复发起")
    # Approval eligibility is computed independently (not gated by contract.status): current version + full-text review + zero missed clauses + score threshold met + no blocking items + content binding
    verdict = approval_gate.evaluate(db, contract)
    verdict.raise_for_status()
    latest_report = verdict.report
    defn = workflow_engine.pick_definition_for_contract(db, contract)
    if not defn:
        raise AppError("WORKFLOW_NO_DEFINITION", 400, "没有可用的流程定义，请先配置审批流")
    snapshot = {
        "score": latest_report.score,
        "contract_type": contract.contract_type,
        "amount": contract.amount,
        "highRisk": latest_report.high_count,
        "riskTotal": latest_report.high_count + latest_report.medium_count + latest_report.low_count,
    }
    inst = workflow_engine.start_instance(
        db, defn, contract, operator.id, operator.real_name or operator.username, snapshot
    )
    if inst.status == "running":
        contract.status = "in_approval"
    contract.updated_at = __import__("datetime").datetime.now()
    db.commit()
    db.refresh(inst)
    write_audit(db, user_id=operator.id, username=operator.username, action="workflow.start",
                resource_type="流程实例", resource_id=str(inst.id), ip=ip, ua=ua,
                extra=f"发起审批（{defn.name} v{defn.version}），评分 {latest_report.score}，高风险 {latest_report.high_count} 项")
    return _inst_out(db, inst)


@router.post("/instances/{instance_id}/actions")
def act_on_instance(
    instance_id: int,
    payload: ActionRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    operator: Annotated[User, Depends(require_perm("workflow:approve"))],
):
    ip, ua = _client_info(request)
    inst = workflow_engine.get_instance_or_404(db, instance_id)
    get_contract_for_user(db, operator, inst.contract_id)
    inst = workflow_engine.act(
        db, inst,
        action=payload.action,
        operator=operator,
        comment=payload.comment,
        expected_node_id=payload.expected_node_id,
    )
    write_audit(db, user_id=operator.id, username=operator.username, action=f"workflow.{payload.action}",
                resource_type="流程实例", resource_id=str(instance_id), ip=ip, ua=ua,
                extra=f"节点 {inst.current_node_id} {inst.current_node_name}")
    return _inst_out(db, inst)


@router.post("/instances/{instance_id}/withdraw")
def withdraw_instance(
    instance_id: int,
    payload: WithdrawRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    operator: Annotated[User, Depends(get_current_user)],
):
    ip, ua = _client_info(request)
    inst = workflow_engine.get_instance_or_404(db, instance_id)
    get_contract_for_user(db, operator, inst.contract_id)
    # Only the initiator (or admin) may withdraw, to prevent withdrawing others' workflows
    is_admin = "admin" in {r.code for r in operator.roles}
    if operator.id != inst.starter_id and not is_admin:
        raise AppError("WORKFLOW_ONLY_STARTER_CAN_WITHDRAW", 403, "仅发起人可撤回该流程")
    inst = workflow_engine.withdraw(db, inst, payload.reason)
    write_audit(db, user_id=operator.id, username=operator.username, action="workflow.withdraw",
                resource_type="流程实例", resource_id=str(instance_id), ip=ip, ua=ua,
                extra=f"撤回原因：{payload.reason[:80]}")
    return _inst_out(db, inst)


@router.post("/instances/{instance_id}/urge")
def urge_instance(
    instance_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    operator: Annotated[User, Depends(require_perm("workflow:start"))],
):
    ip, ua = _client_info(request)
    inst = workflow_engine.get_instance_or_404(db, instance_id)
    get_contract_for_user(db, operator, inst.contract_id)
    inst = workflow_engine.urge(db, inst, operator.real_name or operator.username, operator.username)
    write_audit(db, user_id=operator.id, username=operator.username, action="workflow.urge",
                resource_type="流程实例", resource_id=str(instance_id), ip=ip, ua=ua,
                extra=f"催办节点 {inst.current_node_name}")
    return _inst_out(db, inst)


@router.get("/definitions")
def fetch_definitions(db: Annotated[Session, Depends(get_db)], _: Annotated[User, Depends(get_current_user)]):
    items = db.query(WorkflowDefinition).order_by(WorkflowDefinition.id).all()
    return [workflow_engine.build_definition_out(d) for d in items]


def _ensure_current_definition(db: Session, definition: WorkflowDefinition) -> None:
    successor = db.query(WorkflowDefinition.id).filter(
        WorkflowDefinition.graph["previousDefinitionId"].as_integer() == definition.id
    ).with_for_update().first()
    if successor:
        raise AppError("WORKFLOW_DEF_SUPERSEDED", 409, "该版本已被替代，请编辑最新版本")


@router.post("/definitions")
def save_definition(
    payload: SaveDefinitionRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    operator: Annotated[User, Depends(require_perm("workflow:define"))],
):
    ip, ua = _client_info(request)
    if not (payload.name or "").strip():
        raise AppError("WORKFLOW_NAME_REQUIRED", 400, "请填写流程名称")
    if not payload.contract_types:
        raise AppError("WORKFLOW_TYPE_REQUIRED", 400, "请至少选择一种适用的合同类型")
    if not payload.nodes:
        raise AppError("WORKFLOW_NEED_NODE", 400, "至少需要配置一个业务节点")
    ids = [n.id for n in payload.nodes]
    if len(set(ids)) != len(ids):
        raise AppError("WORKFLOW_DUP_NODE_ID", 400, "存在重复的节点 ID")
    for n in payload.nodes:
        if n.id in {"start", "end"} or not n.id.strip() or len(n.id) > 32:
            raise AppError("WORKFLOW_INVALID_GRAPH", 400, "节点 ID 无效或为保留值")
        if n.type not in {"approval", "condition", "cc"}:
            raise AppError("WORKFLOW_INVALID_GRAPH", 400, "不支持的节点类型")
        if n.risk_threshold is not None and not 0 <= n.risk_threshold <= 100:
            raise AppError("WORKFLOW_INVALID_GRAPH", 400, "风险评分阈值必须在 0 至 100 之间")
        if n.amount_threshold is not None and n.amount_threshold < 0:
            raise AppError("WORKFLOW_INVALID_GRAPH", 400, "金额阈值不能为负数")
        if n.timeout_hours is not None and n.timeout_hours <= 0:
            raise AppError("WORKFLOW_INVALID_GRAPH", 400, "超时时间必须为正数")
        if n.sign_mode is not None and (n.type != "approval" or n.sign_mode not in {"or", "and", "sequence"}):
            raise AppError("WORKFLOW_INVALID_GRAPH", 400, "会签模式无效")

    # Assemble the full node chain: start + business nodes + end; condition rules generated from thresholds (aligned with the frontend orchestrator)
    nodes: list[dict] = [{"id": "start", "type": "start", "name": "发起", "assignees": ["role:business_owner"]}]
    for i, n in enumerate(payload.nodes):
        if n.type == "condition":
            nxt = payload.nodes[i + 1] if i + 1 < len(payload.nodes) else None
            after = payload.nodes[i + 2] if i + 2 < len(payload.nodes) else None
            nodes.append(
                {
                    "id": n.id,
                    "type": "condition",
                    "name": n.name,
                    "rules": [
                        {
                            "when": f"risk_score < {n.risk_threshold if n.risk_threshold is not None else 85} or amount >= {n.amount_threshold if n.amount_threshold is not None else 1000000}",
                            "goto": nxt.id if nxt else "end",
                        },
                        {"when": "default", "goto": after.id if after else "end"},
                    ],
                }
            )
        else:
            node: dict = {"id": n.id, "type": n.type, "name": n.name}
            if n.type == "approval" and n.sign_mode:
                node["signMode"] = n.sign_mode
            if n.assignees:
                node["assignees"] = n.assignees
            if n.timeout_hours:
                node["timeoutHours"] = n.timeout_hours
            nodes.append(node)
    nodes.append({"id": "end", "type": "end", "name": "通过签署", "result": "approved"})

    edges = [{"from": "start", "to": payload.nodes[0].id}]
    for i in range(len(payload.nodes)):
        edges.append({"from": payload.nodes[i].id, "to": payload.nodes[i + 1].id if i + 1 < len(payload.nodes) else "end"})

    import datetime as _dt

    graph = {"nodes": nodes, "edges": edges}
    workflow_engine._nodes_edges(WorkflowDefinition(graph=graph))
    previous = None
    if payload.id:
        previous = db.query(WorkflowDefinition).filter(WorkflowDefinition.id == payload.id).with_for_update().first()
        if previous is None:
            raise AppError("WORKFLOW_DEF_NOT_FOUND", 404, "流程定义不存在")
        _ensure_current_definition(db, previous)
        graph["previousDefinitionId"] = previous.id
        previous.enabled = False
        previous.updated_at = _dt.datetime.now()
    d = WorkflowDefinition(
        name=payload.name, contract_types=payload.contract_types, graph=graph,
        version=previous.version + 1 if previous else 1, enabled=True,
        updated_at=_dt.datetime.now(), created_at=_dt.datetime.now(),
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    write_audit(db, user_id=operator.id, username=operator.username, action="workflow.definition.save",
                resource_type="流程定义", resource_id=f"{d.name} v{d.version}", ip=ip, ua=ua,
                extra="保存流程定义（不可变修改，发布新版本）")
    return workflow_engine.build_definition_out(d)


@router.post("/definitions/{definition_id}/toggle")
def toggle_definition(
    definition_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    operator: Annotated[User, Depends(require_perm("workflow:define"))],
):
    ip, ua = _client_info(request)
    d = db.query(WorkflowDefinition).filter(WorkflowDefinition.id == definition_id).with_for_update().first()
    if d is None:
        raise AppError("WORKFLOW_DEF_NOT_FOUND", 404, "流程定义不存在")
    _ensure_current_definition(db, d)
    if not d.enabled:
        workflow_engine._nodes_edges(d)
    d.enabled = not d.enabled
    d.updated_at = __import__("datetime").datetime.now()
    db.commit()
    db.refresh(d)
    write_audit(db, user_id=operator.id, username=operator.username, action="workflow.definition.toggle",
                resource_type="流程定义", resource_id=f"{d.name} v{d.version}", ip=ip, ua=ua,
                extra="启用" if d.enabled else "停用")
    return workflow_engine.build_definition_out(d)

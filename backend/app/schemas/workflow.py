"""Approval workflow-domain schemas."""
from datetime import datetime
from typing import Any

from pydantic import Field, field_serializer

from app.schemas.common import CamelModel, serialize_dt


class WFNodeOut(CamelModel):
    id: str
    type: str
    name: str
    sign_mode: str | None = Field(default=None, alias="signMode")
    assignees: list[str] | None = None
    timeout_hours: int | None = Field(default=None, alias="timeoutHours")
    rules: list[dict[str, Any]] | None = None
    result: str | None = None


class WFEdgeOut(CamelModel):
    from_: str = Field(alias="from")
    to: str


class WorkflowDefinitionOut(CamelModel):
    id: int
    name: str
    contract_types: list[str] = []
    nodes: list[WFNodeOut] = []
    edges: list[WFEdgeOut] = []
    version: int
    enabled: bool = True
    updated_at: str | None = None

    @field_serializer("updated_at")
    def _ser(self, v: datetime | None):
        return serialize_dt(v)


class DefinitionNodeInput(CamelModel):
    """Workflow composer node input (start / end are fixed by the backend)."""

    id: str
    type: str  # approval / condition / cc
    name: str
    sign_mode: str | None = Field(default=None, alias="signMode")
    assignees: list[str] = []
    timeout_hours: int | None = Field(default=None, alias="timeoutHours")
    risk_threshold: int | None = Field(default=None, alias="riskThreshold")
    amount_threshold: int | None = Field(default=None, alias="amountThreshold")


class SaveDefinitionRequest(CamelModel):
    id: int | None = None
    name: str
    contract_types: list[str] = []
    nodes: list[DefinitionNodeInput] = []


class ContextSnapshotOut(CamelModel):
    score: int = 0
    amount: int = 0
    high_risk: int = Field(default=0, alias="highRisk")
    risk_total: int = Field(default=0, alias="riskTotal")


class ApprovalRecordOut(CamelModel):
    id: int
    instance_id: int
    node_id: str
    node_name: str
    action: str
    operator_name: str
    comment: str
    created_at: str | None = None

    @field_serializer("created_at")
    def _ser(self, v: datetime | None):
        return serialize_dt(v)


class WorkflowInstanceOut(CamelModel):
    id: int
    definition_id: int
    definition_name: str
    definition_version: int
    contract_id: int
    contract_title: str = ""
    current_node_id: str
    current_node_name: str
    status: str
    context_snapshot: ContextSnapshotOut = ContextSnapshotOut()
    starter_name: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    records: list[ApprovalRecordOut] = []

    @field_serializer("started_at", "finished_at")
    def _ser(self, v: datetime | None):
        return serialize_dt(v)


class StartApprovalRequest(CamelModel):
    contract_id: int
    contract_title: str = ""
    score: int = 0
    amount: int = 0
    high_risk: int = Field(default=0, alias="highRisk")
    risk_total: int = Field(default=0, alias="riskTotal")


class ActionRequest(CamelModel):
    expected_node_id: str = Field(alias="expectedNodeId", min_length=1, max_length=32)
    action: str  # approve / reject / return
    comment: str = ""


class WithdrawRequest(CamelModel):
    reason: str = ""

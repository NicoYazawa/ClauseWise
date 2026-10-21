import { http } from '@/api/http'
import type { WorkflowInstance, WorkflowDefinition, ApprovalAction, ContractType } from '@/types'

export async function fetchInstances(): Promise<WorkflowInstance[]> {
  return await http.get<WorkflowInstance[], WorkflowInstance[]>('/workflow/instances')
}

export async function fetchInstance(id: number): Promise<WorkflowInstance> {
  return await http.get<WorkflowInstance, WorkflowInstance>(`/workflow/instances/${id}`)
}

export async function fetchDefinitions(): Promise<WorkflowDefinition[]> {
  return await http.get<WorkflowDefinition[], WorkflowDefinition[]>('/workflow/definitions')
}

/** Approval action: approve/reject/return (writes an audit trace and advances the state machine; transfer/countersign removed, the backend rejects any action other than approve/reject/return) */
export async function actOnInstance(instanceId: number, action: ApprovalAction, comment: string, expectedNodeId: string): Promise<WorkflowInstance> {
  return await http.post<WorkflowInstance, WorkflowInstance>(`/workflow/instances/${instanceId}/actions`, {
    action,
    expectedNodeId,
    comment,
  })
}

/** Initiator withdraws */
export async function withdrawInstance(instanceId: number, reason: string): Promise<WorkflowInstance> {
  return await http.post<WorkflowInstance, WorkflowInstance>(`/workflow/instances/${instanceId}/withdraw`, { reason })
}

/** Start approval from a review report (carries a report-context snapshot used by simpleeval condition evaluation) */
export async function startApproval(input: {
  contractId: number
  contractTitle: string
  score: number
  amount: number
  highRisk: number
  riskTotal: number
}): Promise<WorkflowInstance> {
  return await http.post<WorkflowInstance, WorkflowInstance>('/workflow/instances', input)
}

/** Urge: send an in-app reminder to the current node's handler and record a trace */
export async function urgeInstance(instanceId: number): Promise<WorkflowInstance> {
  return await http.post<WorkflowInstance, WorkflowInstance>(`/workflow/instances/${instanceId}/urge`)
}

/** Workflow editor node input (start / end are fixed and supplied by the backend) */
export interface DefinitionNodeInput {
  id: string
  type: 'approval' | 'condition' | 'cc'
  name: string
  signMode: 'or' | 'and' | 'sequence'
  assignees: string[]
  timeoutHours?: number
  /** Condition node: risk-score threshold (triggered when below) */
  riskThreshold?: number
  /** Condition node: amount threshold (yuan, triggered when not below) */
  amountThreshold?: number
}

/** Save a workflow definition: existing definitions get a new version (immutable edits), new definitions start at v1 */
export async function saveDefinition(input: {
  id?: number
  name: string
  contractTypes: ContractType[]
  nodes: DefinitionNodeInput[]
}): Promise<WorkflowDefinition> {
  return await http.post<WorkflowDefinition, WorkflowDefinition>('/workflow/definitions', input)
}

/** Enable/disable a workflow definition */
export async function toggleDefinition(id: number): Promise<WorkflowDefinition> {
  return await http.post<WorkflowDefinition, WorkflowDefinition>(`/workflow/definitions/${id}/toggle`)
}

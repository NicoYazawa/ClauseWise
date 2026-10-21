/** Multi-agent observability API: registry list + collaboration trace timeline */
import { http } from '@/api/http'
import type { AgentInfo, AgentTraceItem } from '@/types'

/** Agent registry: role list for each collaboration graph (name / duty / tools / owning graph) */
export async function listAgents(): Promise<AgentInfo[]> {
  return await http.get<AgentInfo[], AgentInfo[]>('/agents')
}

/** Multi-agent collaboration timeline for a task (pass the review task id for review; qa is fixed at 0) */
export async function fetchAgentTrace(taskType: 'review' | 'qa', refId: number): Promise<AgentTraceItem[]> {
  return await http.get<AgentTraceItem[], AgentTraceItem[]>('/agents/trace', {
    params: { task_type: taskType, ref_id: refId },
  })
}

/** Recent collaboration traces (data source for the Agent overview page, all types) */
export async function fetchRecentTraces(limit = 60): Promise<AgentTraceItem[]> {
  return await http.get<AgentTraceItem[], AgentTraceItem[]>('/agents/trace/recent', { params: { limit } })
}

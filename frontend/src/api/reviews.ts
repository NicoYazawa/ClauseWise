import { http } from '@/api/http'
import type { ReviewTask, ReviewReport, RiskFinding, ReviewTaskType, FindingStatus } from '@/types'

export async function fetchTasks(): Promise<ReviewTask[]> {
  return await http.get<ReviewTask[], ReviewTask[]>('/review-tasks')
}

export async function fetchTask(taskId: number): Promise<ReviewTask> {
  return await http.get<ReviewTask, ReviewTask>(`/review-tasks/${taskId}`)
}

/** Progress polling: Celery/thread-pool tasks write progress to the DB in real time */
export async function fetchTaskProgress(taskId: number): Promise<{ taskId: number; status: string; progress: number; errorMsg: string | null }> {
  return await http.get(`/review-tasks/${taskId}/progress`)
}

export async function fetchReport(taskId: number): Promise<ReviewReport | null> {
  return await http.get<ReviewReport | null, ReviewReport | null>(`/review-tasks/${taskId}/report`)
}

/** Start a review (real DeepSeek + RAG): full = full-text / clause = single clause / diff = incremental */
export async function startReview(input: {
  contractId: number
  taskType: ReviewTaskType
  /** Base version number for the diff incremental review */
  baseVersionNo?: number
  /** Target clause number for the single-clause review */
  clauseNo?: string
}): Promise<ReviewTask> {
  return await http.post<ReviewTask, ReviewTask>('/review-tasks', input)
}

/** Risk disposition: accept / reject / fixed */
export async function resolveFinding(findingId: number, status: FindingStatus): Promise<RiskFinding> {
  return await http.put<RiskFinding, RiskFinding>(`/findings/${findingId}/status`, { status })
}

/** Audit the report export (3.5.4: AI review report exports are written to the audit log and retained >= 3 years) */
export async function logReportExport(taskId: number, format: 'word' | 'pdf'): Promise<void> {
  await http.post(`/review-tasks/${taskId}/export`, { format })
}

/** All risk findings (data source for the workbench risk-distribution chart) */
export async function fetchFindings(): Promise<RiskFinding[]> {
  return await http.get<RiskFinding[], RiskFinding[]>('/findings')
}

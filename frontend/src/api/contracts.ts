import { http } from '@/api/http'
import type { Contract, ContractType, ContractVersion, ContractClause, ClauseDiffItem } from '@/types'

export interface ContractQuery {
  keyword?: string
  contractType?: ContractType | ''
  status?: string
}

export async function fetchContracts(query: ContractQuery = {}): Promise<Contract[]> {
  const params: Record<string, string> = {}
  if (query.keyword) params.keyword = query.keyword
  if (query.contractType) params.contractType = query.contractType
  if (query.status) params.status = query.status
  return await http.get<Contract[], Contract[]>('/contracts', { params })
}

export async function fetchContract(id: number): Promise<Contract> {
  return await http.get<Contract, Contract>(`/contracts/${id}`)
}

export async function fetchVersions(contractId: number): Promise<ContractVersion[]> {
  return await http.get<ContractVersion[], ContractVersion[]>(`/contracts/${contractId}/versions`)
}

export async function fetchClauses(versionId: number, _contractId?: number): Promise<ContractClause[]> {
  return await http.get<ContractClause[], ContractClause[]>(`/contracts/versions/${versionId}/clauses`)
}

/** Clause-level semantic diff (base/target are version numbers): difflib + vector similarity + LLM diff summarization */
export async function fetchDiff(contractId: number, baseVersion: number, targetVersion: number): Promise<ClauseDiffItem[]> {
  return await http.get<ClauseDiffItem[], ClauseDiffItem[]>(`/contracts/${contractId}/versions/diff`, {
    params: { base: baseVersion, target: targetVersion },
  })
}

/** Upload a new contract: SHA-256 idempotent dedup + async dual-channel parsing (draft → parsing → parsed) */
export async function uploadContract(input: {
  file: File
  title: string
  contractType: ContractType
  counterpartyName: string
  amount: number
}): Promise<Contract> {
  const form = new FormData()
  form.append('file', input.file)
  form.append('title', input.title)
  form.append('contractType', input.contractType)
  form.append('counterpartyName', input.counterpartyName)
  form.append('amount', String(input.amount))
  return await http.post<Contract, Contract>('/contracts/upload', form)
}

/** Upload a revised version of an existing contract (3.1.4 version chain: vN → vN+1, old versions are immutable) */
export async function uploadContractVersion(contractId: number, input: { file: File }): Promise<Contract> {
  const form = new FormData()
  form.append('file', input.file)
  return await http.post<Contract, Contract>(`/contracts/${contractId}/versions`, form)
}

/** Re-parse after a parse failure */
export async function retryParse(contractId: number): Promise<Contract> {
  return await http.post<Contract, Contract>(`/contracts/${contractId}/retry-parse`)
}

/** Archive (soft-delete semantics) */
export async function archiveContract(contractId: number): Promise<Contract> {
  return await http.post<Contract, Contract>(`/contracts/${contractId}/archive`)
}

/** Download: RBAC auth + path-traversal protection; blob triggers the browser save and returns the filename */
export async function downloadContract(contractId: number): Promise<string> {
  const { downloadBlob } = await import('@/api/http')
  const contract = await fetchContract(contractId)
  return await downloadBlob(
    `/contracts/${contractId}/download`,
    `${contract.contractNo}.pdf`,
  )
}

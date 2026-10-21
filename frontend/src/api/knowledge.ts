import { http } from '@/api/http'
import type { LawRegulation, ContractTemplate, ContractType } from '@/types'

export async function fetchLaws(): Promise<LawRegulation[]> {
  return await http.get<LawRegulation[], LawRegulation[]>('/laws')
}

/** Add/edit a law article (new articles auto-submit a vectorization task: BaiLian text-embedding-v4 -> ES) */
export async function saveLaw(input: Omit<LawRegulation, 'id' | 'vectorized' | 'hitCount'> & { id?: number }): Promise<LawRegulation> {
  return await http.post<LawRegulation, LawRegulation>('/laws', input)
}

/** Mark as expired (search filters by effective/expiry; the ES side removes it synchronously) */
export async function markExpired(lawId: number): Promise<LawRegulation> {
  return await http.post<LawRegulation, LawRegulation>(`/laws/${lawId}/expire`)
}

/** Batch Excel import (3.4.1): openpyxl structured parsing + batch vectorization (real BaiLian API) */
export async function importLaws(file: File): Promise<{ imported: number; vectorized: number }> {
  const form = new FormData()
  form.append('file', file)
  return await http.post('/laws/import', form)
}

export async function fetchTemplates(): Promise<ContractTemplate[]> {
  return await http.get<ContractTemplate[], ContractTemplate[]>('/templates')
}

/** Add/edit a template clause: editing bumps the version by 1 (3.4.3 immutable edits, only new versions allowed) */
export async function saveTemplate(input: {
  id?: number
  name: string
  contractType: ContractType
  clauseLevel: ContractTemplate['clauseLevel']
  content: string
}): Promise<ContractTemplate> {
  return await http.post<ContractTemplate, ContractTemplate>('/templates', input)
}

export async function deleteTemplate(id: number): Promise<void> {
  await http.delete(`/templates/${id}`)
}

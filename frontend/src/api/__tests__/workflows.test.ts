/**
 * Critical path: the approval-action API contract.
 * The backend ActionRequest only accepts approve/reject/return + expectedNodeId;
 * the request body must no longer carry the deprecated transferTo (extra fields are silently ignored; this guards against dead params returning).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/http', () => ({
  http: {
    get: vi.fn(),
    post: vi.fn().mockResolvedValue({ id: 1, status: 'running' }),
  },
}))

import { http } from '@/api/http'
import { actOnInstance } from '@/api/workflows'

describe('actOnInstance 请求契约', () => {
  beforeEach(() => {
    vi.mocked(http.post).mockClear()
  })

  it('携带 expectedNodeId 与动作/意见，且不含 transferTo', async () => {
    await actOnInstance(7, 'approve', '同意', 'n1')
    expect(http.post).toHaveBeenCalledWith('/workflow/instances/7/actions', {
      action: 'approve',
      expectedNodeId: 'n1',
      comment: '同意',
    })
    const payload = (http.post as ReturnType<typeof vi.fn>).mock.calls[0][1] as Record<string, unknown>
    expect('transferTo' in payload).toBe(false)
  })

  it('驳回/退回动作均可发出', async () => {
    await actOnInstance(7, 'reject', '不同意', 'n2')
    await actOnInstance(7, 'return', '退回补充', 'n2')
    const actions = (http.post as ReturnType<typeof vi.fn>).mock.calls.map(c => (c[1] as { action: string }).action)
    expect(actions).toEqual(['reject', 'return'])
  })
})

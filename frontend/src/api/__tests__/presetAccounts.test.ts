/**
 * Critical path: the preset (demo) account list on the login page.
 * The backend must return an empty list when the switch is off (no account/password exposure); when on, the frontend's one-click fill depends on this contract.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/http', () => ({ http: { get: vi.fn() } }))

import { http } from '@/api/http'
import { fetchPresetAccounts, type PresetAccountInfo } from '@/api/auth'

const payload: PresetAccountInfo = {
  enabled: true,
  password: 'ClauseWise@2026Demo',
  accounts: [
    {
      username: 'lihuimin',
      realName: '李慧敏',
      deptName: '法务部',
      title: '法务主管',
      roleCode: 'legal_manager',
      roleName: '法务主管',
    },
  ],
}

describe('预制账号清单接口', () => {
  beforeEach(() => {
    vi.mocked(http.get).mockReset()
  })

  it('走未登录可访问的公开端点', async () => {
    vi.mocked(http.get).mockResolvedValue(payload)
    await expect(fetchPresetAccounts()).resolves.toEqual(payload)
    expect(http.get).toHaveBeenCalledWith('/auth/preset-accounts')
  })

  it('开关关闭时口径为空清单，前端不渲染卡片', async () => {
    vi.mocked(http.get).mockResolvedValue({ enabled: false, password: null, accounts: [] })
    const info = await fetchPresetAccounts()
    expect(info.enabled).toBe(false)
    expect(info.password).toBeNull()
    expect(info.accounts).toHaveLength(0)
  })
})

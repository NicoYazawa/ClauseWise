import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AUTH_STORAGE_KEY } from '@/api/http'
import { askQuestionStream } from '@/api/qa'

const encoder = new TextEncoder()

function streamResponse(chunks: string[], status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    body: {
      getReader() {
        let i = 0
        return {
          async read() {
            if (i < chunks.length) return { done: false, value: encoder.encode(chunks[i++]) }
            return { done: true, value: undefined }
          },
        }
      },
    },
  }
}

function errorResponse(body: unknown, jsonThrows = false, status = 500) {
  return {
    ok: false,
    status,
    body: null,
    json: async () => {
      if (jsonThrows) throw new Error('not json')
      return body
    },
  }
}

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('askQuestionStream SSE 流式问答', () => {
  it('按 agent_step → citations → delta → reset → done 顺序回调', async () => {
    const chunks = [
      'data: {"type":"agent_step","agent":"qa_router","role":"路由","summary":"判定为法规问答","detail":{"intent":"law"}}\n\n',
      'data: {"type":"citations","citations":[{"id":1}]}\n\n',
      'data: {"type":"delta","content":"根据"}\n\n',
      'data: {"type":"delta","content":"规定"}\n\n',
      'data: {"type":"reset"}\n\n',
      'data: {"type":"done"}\n\n',
    ]
    vi.stubGlobal('fetch', vi.fn(async () => streamResponse(chunks)))

    const onAgentStep = vi.fn()
    const onCitations = vi.fn()
    const onDelta = vi.fn()
    const onReset = vi.fn()
    const onDone = vi.fn()

    await askQuestionStream('合同有效吗', { onAgentStep, onCitations, onDelta, onReset, onDone })

    expect(onAgentStep).toHaveBeenCalledWith({
      agent: 'qa_router',
      role: '路由',
      summary: '判定为法规问答',
      detail: { intent: 'law' },
    })
    expect(onCitations).toHaveBeenCalledWith([{ id: 1 }])
    expect(onDelta).toHaveBeenNthCalledWith(1, '根据')
    expect(onDelta).toHaveBeenNthCalledWith(2, '规定')
    expect(onReset).toHaveBeenCalled()
    expect(onDone).toHaveBeenCalled()
  })

  it('缺省字段使用默认值（agent/role/summary/detail/citations/content）', async () => {
    const chunks = [
      'data: {"type":"agent_step"}\n\n',
      'data: {"type":"citations"}\n\n',
      'data: {"type":"delta"}\n\n',
      'data: {"type":"done"}\n\n',
    ]
    vi.stubGlobal('fetch', vi.fn(async () => streamResponse(chunks)))

    const onAgentStep = vi.fn()
    const onCitations = vi.fn()
    const onDelta = vi.fn()
    await askQuestionStream('q', { onAgentStep, onCitations, onDelta })

    expect(onAgentStep).toHaveBeenCalledWith({ agent: '', role: '', summary: '', detail: undefined })
    expect(onCitations).toHaveBeenCalledWith([])
    expect(onDelta).toHaveBeenCalledWith('')
  })

  it('缺少回调函数时静默跳过（可选链分支）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        streamResponse([
          'data: {"type":"agent_step"}\n\n',
          'data: {"type":"citations"}\n\n',
          'data: {"type":"delta"}\n\n',
          'data: {"type":"reset"}\n\n',
          'data: {"type":"done"}\n\n',
        ]),
      ),
    )
    await expect(askQuestionStream('q', {})).resolves.toBeUndefined()
  })

  it('忽略没有 data: 行的帧', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => streamResponse(['event: ping\n\n', 'data: {"type":"done"}\n\n'])))
    const onDone = vi.fn()
    await askQuestionStream('q', { onDone })
    expect(onDone).toHaveBeenCalled()
  })

  it('流内 error 事件抛出后端错误信息', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => streamResponse(['data: {"type":"error","detail":"模型生成失败"}\n\n'])))
    await expect(askQuestionStream('q', {})).rejects.toThrow('模型生成失败')
  })

  it('error 事件无 detail 时使用默认文案', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => streamResponse(['data: {"type":"error"}\n\n'])))
    await expect(askQuestionStream('q', {})).rejects.toThrow('模型生成失败，请稍后重试')
  })

  it('有 token 时请求头携带 Bearer', async () => {
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify({ token: 'abc' }))
    const fetchMock = vi.fn(async () => streamResponse(['data: {"type":"done"}\n\n']))
    vi.stubGlobal('fetch', fetchMock)
    await askQuestionStream('q', {})
    const init = fetchMock.mock.calls[0][1] as { headers: Record<string, string> }
    expect(init.headers.Authorization).toBe('Bearer abc')
  })

  it('无 token 时不带 Authorization', async () => {
    const fetchMock = vi.fn(async () => streamResponse(['data: {"type":"done"}\n\n']))
    vi.stubGlobal('fetch', fetchMock)
    await askQuestionStream('q', {})
    const init = fetchMock.mock.calls[0][1] as { headers: Record<string, string> }
    expect(init.headers.Authorization).toBeUndefined()
  })

  describe('错误响应', () => {
    it('detail 为字符串', async () => {
      vi.stubGlobal('fetch', vi.fn(async () => errorResponse({ detail: '无权限访问' })))
      await expect(askQuestionStream('q', {})).rejects.toThrow('无权限访问')
    })

    it('detail 为对象时取 message', async () => {
      vi.stubGlobal('fetch', vi.fn(async () => errorResponse({ detail: { message: '模型繁忙' } })))
      await expect(askQuestionStream('q', {})).rejects.toThrow('模型繁忙')
    })

    it('detail 为对象但无 message 时为空串', async () => {
      vi.stubGlobal('fetch', vi.fn(async () => errorResponse({ detail: {} })))
      await expect(askQuestionStream('q', {})).rejects.toThrow()
    })

    it('非 JSON 响应体回退默认状态码文案', async () => {
      vi.stubGlobal('fetch', vi.fn(async () => errorResponse(undefined, true, 502)))
      await expect(askQuestionStream('q', {})).rejects.toThrow('请求失败（502）')
    })

    it('无 detail 时回退默认状态码文案', async () => {
      vi.stubGlobal('fetch', vi.fn(async () => errorResponse({})))
      await expect(askQuestionStream('q', {})).rejects.toThrow('请求失败（500）')
    })
  })

  it('浏览器不支持流式响应时抛出明确错误', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, body: null })))
    await expect(askQuestionStream('q', {})).rejects.toThrow('当前浏览器不支持流式响应')
  })

  it('跨块拆分的 SSE 帧能被正确拼装', async () => {
    const chunks = ['data: {"type":"del', 'ta","content":"分批"}\n\n', 'data: {"type":"done"}\n\n']
    vi.stubGlobal('fetch', vi.fn(async () => streamResponse(chunks)))
    const onDelta = vi.fn()
    await askQuestionStream('q', { onDelta })
    expect(onDelta).toHaveBeenCalledWith('分批')
  })
})

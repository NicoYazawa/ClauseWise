import { http, readToken } from '@/api/http'
import type { AgentStep, QaCitation } from '@/types'

export interface AskResult {
  answer: string
  citations: QaCitation[]
}

/** RAG Q&A: ES hybrid retrieval (BM25 + kNN, RRF fusion) → DeepSeek generates a cited answer */
export async function askQuestion(question: string): Promise<AskResult> {
  return await http.post<AskResult, AskResult>('/qa/ask', { question })
}

/** Streaming Q&A callbacks: agent decision chain & citations pushed first, generated text appended in chunks */
export interface AskStreamCallbacks {
  /** Agent decision-chain step (intent routing / query planning / quality eval / CRAG correction / SelfRAG reflection) */
  onAgentStep?: (step: AgentStep) => void
  /** Retrieval done, citation list ready (fired before generation; re-pushed after CRAG corrective re-retrieval) */
  onCitations?: (citations: QaCitation[]) => void
  /** Incremental text chunk */
  onDelta?: (text: string) => void
  /** Reflection failed → regeneration: frontend should clear the current answer then re-receive following deltas */
  onReset?: () => void
  /** Normal completion (done event received) */
  onDone?: () => void
}

/**
 * Streaming RAG Q&A: consumes the SSE event stream citations → delta* → done / error.
 * axios cannot read streams, so we use native fetch with a manually attached Bearer token.
 */
export async function askQuestionStream(question: string, cb: AskStreamCallbacks): Promise<void> {
  const token = readToken()
  const resp = await fetch('/api/v1/qa/ask/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ question }),
  })

  if (!resp.ok) {
    let message = `请求失败（${resp.status}）`
    try {
      const data = await resp.json()
      const d = data?.detail
      if (d) message = typeof d === 'string' ? d : (d.message ?? '')
    } catch {
      /* Non-JSON error body: keep the default message */
    }
    throw new Error(message)
  }
  if (!resp.body) throw new Error('当前浏览器不支持流式响应')

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  const consume = (block: string) => {
    const line = block.split('\n').find((l) => l.startsWith('data:'))
    if (!line) return
    const evt = JSON.parse(line.slice(5).trim()) as {
      type: 'agent_step' | 'citations' | 'delta' | 'reset' | 'done' | 'error'
      agent?: string
      role?: string
      summary?: string
      detail?: Record<string, unknown> | string
      citations?: QaCitation[]
      content?: string
    }
    if (evt.type === 'agent_step')
      cb.onAgentStep?.({
        agent: evt.agent ?? '',
        role: evt.role ?? '',
        summary: evt.summary ?? '',
        detail: typeof evt.detail === 'object' ? evt.detail : undefined,
      })
    else if (evt.type === 'citations') cb.onCitations?.(evt.citations ?? [])
    else if (evt.type === 'delta') cb.onDelta?.(evt.content ?? '')
    else if (evt.type === 'reset') cb.onReset?.()
    else if (evt.type === 'error') throw new Error((evt.detail as string) || '模型生成失败，请稍后重试')
  }

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    // SSE frames are separated by blank lines; extract every complete frame in a loop
    let idx: number
    while ((idx = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      consume(block)
    }
  }
  cb.onDone?.()
}

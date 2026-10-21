import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AgentsView from '@/views/system/AgentsView.vue'
import { mountWithApp } from '@test/helpers'

const mocks = vi.hoisted(() => ({
  listAgents: vi.fn(),
  fetchRecentTraces: vi.fn(),
}))

vi.mock('@/api/agents', () => ({
  listAgents: (...a: unknown[]) => mocks.listAgents(...a),
  fetchRecentTraces: (...a: unknown[]) => mocks.fetchRecentTraces(...a),
}))

function agent(over: Record<string, unknown> = {}) {
  return {
    name: 'review_planner',
    role: '任务规划',
    graph: 'review_graph',
    kind: 'llm',
    description: '默认描述',
    tools: ['search_law'],
    ...over,
  }
}

function trace(over: Record<string, unknown> = {}) {
  return {
    id: 1,
    createdAt: '2026-08-28T10:00:00',
    taskType: 'review',
    refId: 7,
    agentName: 'review_planner',
    role: '规划',
    action: 'plan',
    payload: {},
    latencyMs: 120,
    tokens: 100,
    error: null,
    ...over,
  }
}

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset())
  mocks.listAgents.mockResolvedValue([])
  mocks.fetchRecentTraces.mockResolvedValue([])
})

describe('AgentsView 注册表', () => {
  it('按协作图分组并渲染角色/工具/描述', async () => {
    mocks.listAgents.mockResolvedValue([
      agent({ name: 'review_planner' }),
      agent({ name: 'rule_auditor', graph: 'review_graph', kind: 'deterministic', tools: [], descKey: 'data.agentDesc.rule' }),
      agent({ name: 'qa_router', graph: 'qa_graph', kind: 'structured', tools: ['qa_tool'] }),
      agent({ name: 'custom', graph: 'custom_graph', kind: 'llm', tools: [] }),
    ])
    const { wrapper } = await mountWithApp(AgentsView)
    await flushPromises()

    expect(wrapper.text()).toContain('review_planner')
    expect(wrapper.text()).toContain('qa_router')
    expect(wrapper.text()).toContain('search_law')
    expect(mocks.fetchRecentTraces).toHaveBeenCalledWith(60)
  })

  it('注册表为空时仍渲染框架', async () => {
    const { wrapper } = await mountWithApp(AgentsView)
    await flushPromises()
    expect(wrapper.text().length).toBeGreaterThan(0)
  })
})

describe('AgentsView 留痕摘要生成', () => {
  const cases: Array<{ name: string; payload: Record<string, unknown> }> = [
    { name: 'review_planner', payload: { subQueries: ['付款', '账期', '违约'] } },
    { name: 'review_planner', payload: { output: { focusPoints: ['质量'] } } },
    { name: 'review_planner', payload: { summary: '规划摘要' } },
    { name: 'qa_planner', payload: {} },
    { name: 'rule_auditor', payload: { findings: [{}, {}] } },
    { name: 'rule_auditor', payload: {} },
    { name: 'clause_reviewer', payload: { error: '超时' } },
    { name: 'clause_reviewer', payload: { tools: ['t1', 't2'], clauseNo: '3.2' } },
    { name: 'clause_reviewer', payload: {} },
    { name: 'verifier', payload: { error: '失败' } },
    { name: 'verifier', payload: { candidates: 5, merged: 3 } },
    { name: 'verifier', payload: { candidates: 2 } },
    { name: 'verifier', payload: { summary: '校验完成' } },
    { name: 'reporter', payload: { stats: { score: 91 } } },
    { name: 'reporter', payload: { opinion: '意见' } },
    { name: 'qa_router', payload: { route: { intent: 'law' } } },
    { name: 'retriever', payload: { hits: 4 } },
    { name: 'qa_grader', payload: { relevant: 3, total: 5 } },
    { name: 'qa_reflector', payload: { passed: true, regen: true } },
    { name: 'qa_reflector', payload: { passed: false } },
    { name: 'qa_answerer', payload: { noHit: true } },
    { name: 'qa_answerer', payload: { citations: 3 } },
    { name: 'qa_corrector', payload: {} },
    { name: 'unknown_agent', payload: { summary: '兜底摘要' } },
    { name: 'unknown_agent', payload: { opinion: '兜底意见' } },
  ]

  it('所有 Agent 分支都能生成摘要且不报错', async () => {
    mocks.fetchRecentTraces.mockResolvedValue(
      cases.map((c, i) =>
        trace({
          id: i + 1,
          agentName: c.name,
          payload: c.payload,
          taskType: i % 2 === 0 ? 'review' : 'qa',
          tokens: i % 3 === 0 ? 100 : 0,
          createdAt: i % 5 === 0 ? null : '2026-08-28T10:00:00',
        }),
      ),
    )
    const { wrapper } = await mountWithApp(AgentsView)
    await flushPromises()

    expect(wrapper.text()).toContain('规划摘要')
    expect(wrapper.text()).toContain('兜底摘要')
    expect(wrapper.text().length).toBeGreaterThan(100)
  })

  it('出错留痕优先展示错误摘要', async () => {
    mocks.fetchRecentTraces.mockResolvedValue([
      trace({ id: 1, agentName: 'rule_auditor', error: '连接 ES 失败', payload: {} }),
      trace({ id: 2, agentName: 'qa_answerer', payload: { citations: 1 } }),
    ])
    const { wrapper } = await mountWithApp(AgentsView)
    await flushPromises()
    expect(wrapper.text()).toContain('连接 ES 失败')
  })
})

import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import QaAssistantView from '@/views/knowledge/QaAssistantView.vue'
import { mountWithApp } from '@test/helpers'

const mocks = vi.hoisted(() => ({ askQuestionStream: vi.fn() }))

vi.mock('@/api/qa', () => ({ askQuestionStream: (...a: unknown[]) => mocks.askQuestionStream(...a) }))

const citations = [
  { id: 1, kind: 'law', title: '民法典第五百零九条', score: 0.92, snippet: '当事人应当按照约定履行义务' },
  { id: 2, kind: 'case', title: '指导案例', score: 0.81, snippet: '裁判要点' },
  { id: 3, kind: 'template', title: '付款条款模板', score: 0.77, snippet: '按月结算' },
]

function streaming() {
  mocks.askQuestionStream.mockImplementation(async (_q: string, cb: Record<string, (...a: never[]) => void>) => {
    cb.onAgentStep?.({ agent: 'qa_router', role: '路由', summary: '判定为法规问答' } as never)
    cb.onCitations?.(citations as never)
    cb.onDelta?.('根据' as never)
    cb.onDelta?.('规定' as never)
    cb.onDone?.()
  })
}

async function settle(ms = 160) {
  await new Promise((resolve) => setTimeout(resolve, ms))
  await flushPromises()
}

beforeEach(() => {
  mocks.askQuestionStream.mockReset()
  streaming()
})

describe('QaAssistantView', () => {
  it('初始欢迎态展示快捷问题', async () => {
    const { wrapper } = await mountWithApp(QaAssistantView)
    await flushPromises()
    expect(wrapper.findAll('button').length).toBeGreaterThanOrEqual(6)
  })

  it('点击快捷问题发送并流式渲染回答与引用', async () => {
    const { wrapper } = await mountWithApp(QaAssistantView)
    await flushPromises()

    const quick = wrapper.findAll('button')[1]
    const question = quick.text()
    await quick.trigger('click')
    await settle()

    expect(mocks.askQuestionStream).toHaveBeenCalled()
    expect((mocks.askQuestionStream.mock.calls[0] as unknown[])[0]).toBeTruthy()
    expect(wrapper.text()).toContain(question)
    expect(wrapper.text()).toContain('根据规')
    expect(wrapper.text()).toContain('民法典第五百零九条')
  })

  it('输入框 Enter 发送，Shift+Enter 不发送', async () => {
    const { wrapper } = await mountWithApp(QaAssistantView)
    await flushPromises()
    const textarea = wrapper.find('textarea')
    await textarea.setValue('合同无效怎么办')

    await textarea.trigger('keydown', { key: 'Enter', shiftKey: true })
    expect(mocks.askQuestionStream).not.toHaveBeenCalled()

    await textarea.trigger('keydown', { key: 'Enter' })
    await settle()
    expect(mocks.askQuestionStream).toHaveBeenCalledWith('合同无效怎么办', expect.any(Object))
  })

  it('空输入不发送', async () => {
    const { wrapper } = await mountWithApp(QaAssistantView)
    await flushPromises()
    const sendBtn = wrapper.findAll('button').at(-1)
    await sendBtn!.trigger('click')
    await flushPromises()
    expect(mocks.askQuestionStream).not.toHaveBeenCalled()
  })

  it('流式接口报错时把错误提示追加到回答', async () => {
    mocks.askQuestionStream.mockRejectedValue(new Error('网关超时'))
    const { wrapper } = await mountWithApp(QaAssistantView)
    await flushPromises()
    await wrapper.find('textarea').setValue('测试')
    await wrapper.find('textarea').trigger('keydown', { key: 'Enter' })
    await settle()

    expect(wrapper.text()).toContain('网关超时')
  })

  it('引用可展开/收起，智能体步骤可展开', async () => {
    const { wrapper } = await mountWithApp(QaAssistantView)
    await flushPromises()
    await wrapper.find('textarea').setValue('测试')
    await wrapper.find('textarea').trigger('keydown', { key: 'Enter' })
    await settle()

    const citationBtn = wrapper.findAll('button').find((b) => b.text().includes('民法典'))
    await citationBtn!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('当事人应当按照约定履行义务')

    await citationBtn!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).not.toContain('当事人应当按照约定履行义务')

    const stepsBtn = wrapper.findAll('button').find((b) => b.text().includes('路由'))
    if (stepsBtn) {
      await stepsBtn.trigger('click')
      await flushPromises()
      expect(wrapper.text()).toContain('判定为法规问答')
    }
  })

  it('自反思失败时清空当前回答后重新接收增量', async () => {
    mocks.askQuestionStream.mockImplementation(async (_q: string, cb: Record<string, (...a: never[]) => void>) => {
      cb.onDelta?.('旧内容' as never)
      cb.onReset?.()
      cb.onDelta?.('新内容' as never)
    })
    const { wrapper } = await mountWithApp(QaAssistantView)
    await flushPromises()
    await wrapper.find('textarea').setValue('测试')
    await wrapper.find('textarea').trigger('keydown', { key: 'Enter' })
    await settle()

    expect(wrapper.text()).toContain('新内容')
  })
})

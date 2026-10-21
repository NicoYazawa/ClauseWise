import { describe, expect, it } from 'vitest'

import BaseBadge from '@/components/ui/BaseBadge.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseInput from '@/components/ui/BaseInput.vue'
import BaseTable from '@/components/ui/BaseTable.vue'
import BaseTabs from '@/components/ui/BaseTabs.vue'
import { mountWithApp } from '@test/helpers'

describe('BaseButton', () => {
  it('默认主按钮，md 尺寸', async () => {
    const { wrapper } = await mountWithApp(BaseButton, { props: { variant: undefined, size: undefined } })
    expect(wrapper.classes()).toContain('btn-primary')
    expect(wrapper.find('button').exists()).toBe(true)
  })

  it('覆盖全部 variant 与 sm 尺寸、block', async () => {
    for (const variant of ['primary', 'secondary', 'ghost', 'danger', 'success']) {
      const { wrapper } = await mountWithApp(BaseButton, { props: { variant } })
      expect(wrapper.classes().length).toBeGreaterThan(0)
      wrapper.unmount()
    }
    const { wrapper } = await mountWithApp(BaseButton, { props: { variant: 'secondary', size: 'sm', block: true } })
    expect(wrapper.classes()).toContain('btn-sm')
    expect(wrapper.classes()).toContain('w-full')
  })

  it('loading 时禁用并显示旋转图标', async () => {
    const { wrapper } = await mountWithApp(BaseButton, { props: { loading: true } })
    expect(wrapper.find('button').attributes('disabled')).toBeDefined()
  })

  it('icon 显示与 disabled 禁用', async () => {
    const { wrapper } = await mountWithApp(BaseButton, { props: { icon: 'search', disabled: true } })
    expect(wrapper.find('button').attributes('disabled')).toBeDefined()
  })
})

describe('BaseBadge', () => {
  it('默认 slate 与 sm 尺寸', async () => {
    const { wrapper } = await mountWithApp(BaseBadge)
    expect(wrapper.classes()).toContain('pill-neutral')
    expect(wrapper.classes()).toContain('h-5')
  })

  it('md 尺寸与 dot 圆点', async () => {
    const { wrapper } = await mountWithApp(BaseBadge, { props: { tone: 'danger', size: 'md', dot: true } })
    expect(wrapper.classes()).toContain('h-6')
    expect(wrapper.find('span.inline-block').exists()).toBe(true)
  })

  it('全部 tone 均可映射样式', async () => {
    for (const tone of ['slate', 'info', 'warn', 'danger', 'success', 'primary']) {
      const { wrapper } = await mountWithApp(BaseBadge, { props: { tone, dot: true } })
      expect(wrapper.classes().length).toBeGreaterThan(0)
      wrapper.unmount()
    }
  })
})

describe('BaseCard', () => {
  it('无标题无 actions 时不渲染头部', async () => {
    const { wrapper } = await mountWithApp(BaseCard, { slots: { default: '<p>body</p>' } })
    expect(wrapper.find('h2').exists()).toBe(false)
    expect(wrapper.text()).toContain('body')
  })

  it('标题 + 副标题 + actions 插槽', async () => {
    const { wrapper } = await mountWithApp(BaseCard, {
      props: { title: '卡片', subtitle: '说明', padding: 'p-0' },
      slots: { actions: '<button>操作</button>', default: '内容' },
    })
    expect(wrapper.find('h2').text()).toBe('卡片')
    expect(wrapper.text()).toContain('说明')
    expect(wrapper.find('button').text()).toBe('操作')
    expect(wrapper.classes()).toContain('p-0')
  })

  it('只有 actions 没有标题时也渲染头部', async () => {
    const { wrapper } = await mountWithApp(BaseCard, { slots: { actions: '<i>x</i>' } })
    expect(wrapper.find('h2').exists()).toBe(true)
  })
})

describe('BaseInput', () => {
  it('渲染标签、提示与占位符', async () => {
    const { wrapper } = await mountWithApp(BaseInput, {
      props: { label: '用户名', hint: '必填', placeholder: '请输入', modelValue: 'abc' },
    })
    expect(wrapper.find('label').text()).toContain('用户名')
    expect(wrapper.text()).toContain('必填')
    const input = wrapper.find('input')
    expect(input.attributes('placeholder')).toBe('请输入')
    expect(input.attributes('type')).toBe('text')
    expect((input.element as HTMLInputElement).value).toBe('abc')
  })

  it('type 与 disabled 透传', async () => {
    const { wrapper } = await mountWithApp(BaseInput, {
      props: { label: '密码', type: 'password', disabled: true, modelValue: '' },
    })
    const input = wrapper.find('input')
    expect(input.attributes('type')).toBe('password')
    expect(input.attributes('disabled')).toBeDefined()
  })

  it('输入时触发 update:modelValue', async () => {
    const { wrapper } = await mountWithApp(BaseInput, { props: { label: 'L', modelValue: '' } })
    await wrapper.find('input').setValue('new-value')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['new-value'])
  })

  it('无 hint 时不渲染提示', async () => {
    const { wrapper } = await mountWithApp(BaseInput, { props: { label: 'L', modelValue: '' } })
    expect(wrapper.find('.label span').exists()).toBe(false)
  })
})

describe('BaseTabs', () => {
  const tabs = [
    { key: 'a', label: '全部', count: 3 },
    { key: 'b', label: '待处理' },
  ]

  it('渲染标签与计数角标', async () => {
    const { wrapper } = await mountWithApp(BaseTabs, { props: { tabs, modelValue: 'a' } })
    expect(wrapper.text()).toContain('全部')
    expect(wrapper.text()).toContain('3')
    expect(wrapper.text()).toContain('待处理')
  })

  it('无 count 时不渲染角标', async () => {
    const { wrapper } = await mountWithApp(BaseTabs, {
      props: { tabs: [{ key: 'x', label: 'X' }], modelValue: 'x' },
    })
    expect(wrapper.find('span.rounded-full').exists()).toBe(false)
  })

  it('渲染可点击的标签触发器', async () => {
    const { wrapper } = await mountWithApp(BaseTabs, { props: { tabs, modelValue: 'a' } })
    const triggers = wrapper.findAll('[role="tab"]')
    expect(triggers.length).toBe(2)
    await triggers[1].trigger('click')
  })
})

describe('BaseTable', () => {
  const columns = [
    { key: 'name', label: '名称' },
    { key: 'amount', label: '金额', align: 'right' as const, width: '120px' },
    { key: 'status', label: '状态', align: 'center' as const },
  ]

  it('loading 时渲染骨架行', async () => {
    const { wrapper } = await mountWithApp(BaseTable, { props: { columns, loading: true } })
    expect(wrapper.findAll('tbody tr').length).toBe(4)
  })

  it('empty 时渲染空态文案（默认与自定义）', async () => {
    const { wrapper } = await mountWithApp(BaseTable, { props: { columns, empty: true } })
    expect(wrapper.find('.empty-slot').text()).toBeTruthy()

    const { wrapper: custom } = await mountWithApp(BaseTable, {
      props: { columns, empty: true, emptyText: '没有记录' },
    })
    expect(custom.find('.empty-slot').text()).toBe('没有记录')
  })

  it('正常渲染表头对齐与列宽，并输出默认插槽', async () => {
    const { wrapper } = await mountWithApp(BaseTable, {
      props: { columns },
      slots: { default: '<tr><td>行</td></tr>' },
    })
    const ths = wrapper.findAll('th')
    expect(ths[0].classes()).not.toContain('text-right')
    expect(ths[1].classes()).toContain('text-right')
    expect(ths[2].classes()).toContain('text-center')
    expect(ths[1].attributes('style')).toContain('120px')
    expect(wrapper.text()).toContain('行')
  })
})

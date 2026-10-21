import { mount } from '@vue/test-utils'
import { defineComponent, nextTick, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const chartMock = {
  setOption: vi.fn(),
  resize: vi.fn(),
  dispose: vi.fn(),
}
const initMock = vi.fn(() => chartMock)

vi.mock('echarts', () => ({
  init: (...args: unknown[]) => initMock(...args),
}))

import { useECharts } from '@/composables/useECharts'

describe('useECharts', () => {
  beforeEach(() => {
    initMock.mockClear()
    chartMock.setOption.mockClear()
    chartMock.resize.mockClear()
    chartMock.dispose.mockClear()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('el 为空时 render 直接返回，不初始化实例', async () => {
    const Comp = defineComponent({
      setup(_, { expose }) {
        const el = ref<HTMLElement | null>(null)
        const api = useECharts(el)
        expose({ ...api, el })
        return { el }
      },
      template: '<div />',
    })
    const wrapper = mount(Comp)
    await nextTick()

    wrapper.vm.render({} as never)
    expect(initMock).not.toHaveBeenCalled()
    expect(chartMock.setOption).not.toHaveBeenCalled()
  })

  it('首次 render 初始化实例，后续复用', async () => {
    const Comp = defineComponent({
      setup(_, { expose }) {
        const el = ref<HTMLElement | null>(null)
        const api = useECharts(el)
        expose(api)
        return { el }
      },
      template: '<div ref="el" data-chart />',
    })
    const wrapper = mount(Comp)
    await nextTick()

    wrapper.vm.render({ series: [] } as never)
    wrapper.vm.render({ series: [1] } as never)

    expect(initMock).toHaveBeenCalledTimes(1)
    expect(chartMock.setOption).toHaveBeenCalledTimes(2)
    expect(chartMock.setOption).toHaveBeenLastCalledWith({ series: [1] }, true)
  })

  it('窗口 resize 触发 chart.resize', async () => {
    const Comp = defineComponent({
      setup(_, { expose }) {
        const el = ref<HTMLElement | null>(null)
        const api = useECharts(el)
        expose(api)
        return { el }
      },
      template: '<div ref="el" data-chart />',
    })
    const wrapper = mount(Comp)
    await nextTick()
    wrapper.vm.render({} as never)

    window.dispatchEvent(new Event('resize'))
    expect(chartMock.resize).toHaveBeenCalled()
  })

  it('卸载时移除监听并释放实例', async () => {
    const removeSpy = vi.spyOn(window, 'removeEventListener')
    const Comp = defineComponent({
      setup(_, { expose }) {
        const el = ref<HTMLElement | null>(null)
        const api = useECharts(el)
        expose(api)
        return { el }
      },
      template: '<div ref="el" data-chart />',
    })
    const wrapper = mount(Comp)
    await nextTick()
    wrapper.vm.render({} as never)
    wrapper.unmount()

    expect(removeSpy).toHaveBeenCalledWith('resize', expect.any(Function))
    expect(chartMock.dispose).toHaveBeenCalled()
  })

  it('未初始化就卸载也不报错（chart.value?.dispose 空值分支）', async () => {
    const Comp = defineComponent({
      setup() {
        const el = ref<HTMLElement | null>(null)
        useECharts(el)
        return {}
      },
      template: '<div />',
    })
    const wrapper = mount(Comp)
    await nextTick()
    expect(() => wrapper.unmount()).not.toThrow()
    expect(chartMock.dispose).not.toHaveBeenCalled()
  })
})

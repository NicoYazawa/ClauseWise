import { flushPromises } from '@vue/test-utils'
import { useQueryClient } from '@tanstack/vue-query'
import { defineComponent } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import { useApiDetail, useApiList, useApiMutation } from '@/composables/useApiQuery'
import { mountWithApp } from '@test/helpers'

describe('useApiList', () => {
  it('data 收敛为数组，加载完成后可读', async () => {
    const Comp = defineComponent({
      setup() {
        const { list, loading, initialLoading, error, reload } = useApiList(['list'], async () => [
          { id: 1 },
          { id: 2 },
        ])
        return { list, loading, initialLoading, error, reload }
      },
      template: '<div><span class="n">{{ list.length }}</span><i class="loading">{{ loading }}</i><i class="init">{{ initialLoading }}</i><i class="err">{{ error ? "yes" : "no" }}</i></div>',
    })

    const { wrapper } = await mountWithApp(Comp)
    await flushPromises()

    expect(wrapper.find('.n').text()).toBe('2')
    expect(wrapper.find('.loading').text()).toBe('false')
    expect(wrapper.find('.init').text()).toBe('false')
    expect(wrapper.find('.err').text()).toBe('no')
  })

  it('请求失败时 error 有值，list 仍为空数组', async () => {
    const boom = new Error('boom')
    const Comp = defineComponent({
      setup() {
        const { list, error } = useApiList(['list', 'err'], async () => {
          throw boom
        })
        return { list, error }
      },
      template: '<div><span class="n">{{ list.length }}</span><i class="err">{{ error ? error.message : "" }}</i></div>',
    })

    const { wrapper } = await mountWithApp(Comp)
    await flushPromises()

    expect(wrapper.find('.n').text()).toBe('0')
    expect(wrapper.find('.err').text()).toBe('boom')
  })
})

describe('useApiDetail', () => {
  it('返回单对象，初始为 undefined，加载后填充', async () => {
    const Comp = defineComponent({
      setup() {
        const { data, loading } = useApiDetail(['detail'], async () => ({ id: 9 }))
        return { data, loading }
      },
      template: '<div><span class="id">{{ data ? data.id : "none" }}</span><i class="loading">{{ loading }}</i></div>',
    })

    const { wrapper } = await mountWithApp(Comp)
    await flushPromises()
    expect(wrapper.find('.id').text()).toBe('9')
    expect(wrapper.find('.loading').text()).toBe('false')
  })
})

describe('useApiMutation', () => {
  it('成功后按单个 key 失效并回调', async () => {
    const invalidate = vi.fn().mockResolvedValue(undefined)
    const onSuccess = vi.fn()
    const Comp = defineComponent({
      setup() {
        const qc = useQueryClient()
        vi.spyOn(qc, 'invalidateQueries').mockImplementation(invalidate)
        const m = useApiMutation(async (v: number) => v * 2, { invalidate: ['x'], onSuccess })
        return { m }
      },
      template: '<div />',
    })

    const { wrapper } = await mountWithApp(Comp)
    await wrapper.vm.m.mutateAsync(3)
    await flushPromises()

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['x'] })
    expect(onSuccess).toHaveBeenCalledWith(6, 3)
  })

  it('多个 key 时并发失效', async () => {
    const invalidate = vi.fn().mockResolvedValue(undefined)
    const Comp = defineComponent({
      setup() {
        const qc = useQueryClient()
        vi.spyOn(qc, 'invalidateQueries').mockImplementation(invalidate)
        const m = useApiMutation(async () => 'ok', { invalidate: [['a'], ['b']] })
        return { m }
      },
      template: '<div />',
    })

    const { wrapper } = await mountWithApp(Comp)
    await wrapper.vm.m.mutateAsync(undefined)
    await flushPromises()
    expect(invalidate).toHaveBeenCalledTimes(2)
  })

  it('未配置 invalidate 时不失效，仅执行 onSuccess', async () => {
    const onSuccess = vi.fn()
    const Comp = defineComponent({
      setup() {
        const qc = useQueryClient()
        const spy = vi.spyOn(qc, 'invalidateQueries').mockResolvedValue(undefined)
        const m = useApiMutation(async () => 1, { onSuccess })
        return { m, spy }
      },
      template: '<div />',
    })

    const { wrapper } = await mountWithApp(Comp)
    await wrapper.vm.m.mutateAsync(undefined)
    await flushPromises()
    expect(wrapper.vm.spy).not.toHaveBeenCalled()
    expect(onSuccess).toHaveBeenCalledWith(1, undefined)
  })

  it('失败时触发 onError', async () => {
    const onError = vi.fn()
    const err = new Error('nope')
    const Comp = defineComponent({
      setup() {
        const m = useApiMutation(async () => {
          throw err
        }, { onError })
        return { m }
      },
      template: '<div />',
    })

    const { wrapper } = await mountWithApp(Comp)
    await expect(wrapper.vm.m.mutateAsync(undefined)).rejects.toThrow('nope')
    expect(onError).toHaveBeenCalled()
  })
})

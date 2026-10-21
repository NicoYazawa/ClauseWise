import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter, type Router, type RouteRecordRaw } from 'vue-router'
import { defineComponent, type Component, type Plugin } from 'vue'

import enUS from '@/i18n/locales/en-US'
import zhCN from '@/i18n/locales/zh-CN'

/** Placeholder route component used by the memory router. */
export const Dummy = defineComponent({ name: 'Dummy', template: '<div class="dummy" />' })

export function makeI18n(locale: 'zh-CN' | 'en-US' = 'zh-CN') {
  return createI18n({
    legacy: false,
    locale,
    fallbackLocale: 'zh-CN',
    messages: { 'zh-CN': zhCN, 'en-US': enUS },
  })
}

export function makeRouter(initialPath = '/', routes?: RouteRecordRaw[]): Router {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: routes ?? [{ path: '/:pathMatch(.*)*', component: Dummy }],
  })
  void router.push(initialPath)
  return router
}

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  })
}

export interface MountOptions {
  props?: Record<string, unknown>
  slots?: Record<string, unknown>
  router?: Router
  initialPath?: string
  routes?: RouteRecordRaw[]
  queryClient?: QueryClient
  pinia?: Pinia
  stubs?: Record<string, unknown>
  attachTo?: HTMLElement
  locale?: 'zh-CN' | 'en-US'
}

export interface Mounted {
  wrapper: VueWrapper
  router: Router
  queryClient: QueryClient
  pinia: Pinia
}

/** Mount a component with the standard app plugins (i18n / pinia / router / vue-query). */
export async function mountWithApp(component: Component, options: MountOptions = {}): Promise<Mounted> {
  const router = options.router ?? makeRouter(options.initialPath ?? '/', options.routes)
  await router.isReady()
  const queryClient = options.queryClient ?? makeQueryClient()
  const pinia = options.pinia ?? createPinia()
  setActivePinia(pinia)
  const i18n = makeI18n(options.locale ?? 'zh-CN')
  const wrapper = mount(component, {
    props: options.props,
    slots: options.slots as never,
    attachTo: options.attachTo,
    global: {
      plugins: [i18n, pinia, router, [VueQueryPlugin, { queryClient }] as unknown as Plugin],
      stubs: options.stubs,
    },
  })
  await flushPromises()
  return { wrapper, router, queryClient, pinia }
}

/** Minimal project fixtures shared by view tests. */
export function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json' },
    status: 200,
    ...init,
  })
}

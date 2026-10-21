import { QueryClient } from '@tanstack/vue-query'

/**
 * Global QueryClient.
 *
 * Default strategy:
 * - staleTime 30s: list data is reused within 30s to avoid repeated requests when paging
 * - retry 1: retry once on failure (401 is handled uniformly by the axios interceptor, so it is not retried)
 * - refetchOnWindowFocus false: avoid hammering the API when switching back to the window
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: 0,
    },
  },
})
import { computed, type MaybeRefOrGetter } from 'vue'
import { useMutation, useQuery, useQueryClient, type QueryKey, type UseQueryOptions } from '@tanstack/vue-query'

/**
 * Lightweight wrapper around TanStack Query (one-line integration for list pages).
 *
 * Unlike using useQuery directly, here `data` is narrowed to an array that is
 * **never undefined**, so view templates and scripts can keep using `items.length`
 * / `items.value.filter(...)` without writing `?? []` in every view.
 *
 * Caching / dedup / invalidation / retry / background refresh are all provided by TanStack Query.
 */
export function useApiList<T>(
  queryKey: MaybeRefOrGetter<QueryKey>,
  queryFn: () => Promise<T[]>,
  options?: Omit<UseQueryOptions<T[]>, 'queryKey' | 'queryFn'>,
) {
  const query = useQuery({ queryKey, queryFn, ...options })
  return {
    /** List data (always an array) */
    list: computed(() => query.data.value ?? []),
    /** First load or background refresh in progress */
    loading: computed(() => query.isLoading.value || query.isFetching.value),
    /** First load only (can distinguish the skeleton state from a refresh) */
    initialLoading: computed(() => query.isLoading.value),
    error: computed(() => query.error.value),
    reload: query.refetch,
  }
}

/** Single-object query (detail page) */
export function useApiDetail<T>(
  queryKey: MaybeRefOrGetter<QueryKey>,
  queryFn: () => Promise<T>,
  options?: Omit<UseQueryOptions<T>, 'queryKey' | 'queryFn'>,
) {
  const query = useQuery({ queryKey, queryFn, ...options })
  return {
    data: computed(() => query.data.value),
    loading: computed(() => query.isLoading.value || query.isFetching.value),
    error: computed(() => query.error.value),
    reload: query.refetch,
  }
}

/**
 * Mutation wrapper: automatically invalidates the given query keys on success
 * (defaults to invalidating all caches in that business domain).
 */
export function useApiMutation<TVars = void, TData = unknown>(
  mutationFn: (vars: TVars) => Promise<TData>,
  options?: {
    /** Query keys to invalidate on success */
    invalidate?: QueryKey | QueryKey[]
    onSuccess?: (data: TData, vars: TVars) => void | Promise<void>
    onError?: (error: unknown, vars: TVars) => void
  },
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: async (data, vars) => {
      const invalidate = options?.invalidate
      if (invalidate) {
        // A QueryKey is itself an array, so a plain `Array.isArray` check would split
        // `['system', 'users']` into two keys and invalidate the wrong caches.
        const keys: QueryKey[] =
          Array.isArray(invalidate) && Array.isArray(invalidate[0])
            ? (invalidate as QueryKey[])
            : [invalidate as QueryKey]
        await Promise.all(keys.map((key) => queryClient.invalidateQueries({ queryKey: key })))
      }
      await options?.onSuccess?.(data, vars)
    },
    onError: (error, vars) => {
      options?.onError?.(error, vars)
    },
  })
}
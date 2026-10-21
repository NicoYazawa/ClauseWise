<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

defineProps<{
  columns: Array<{ key: string; label: string; width?: string; align?: 'left' | 'right' | 'center' }>
  loading?: boolean
  empty?: boolean
  emptyText?: string
}>()
</script>

<template>
  <div class="overflow-x-auto">
    <table class="w-full border-collapse">
      <!-- Header: 12px gray, sentence-case caps (no band, no divider) -->
      <thead>
        <tr>
          <th
            v-for="col in columns"
            :key="col.key"
            class="table-th"
            :class="col.align === 'right' ? 'text-right' : col.align === 'center' ? 'text-center' : ''"
            :style="col.width ? { width: col.width } : undefined"
          >
            {{ col.label }}
          </th>
        </tr>
      </thead>

      <!-- Loading: keep the final layout, use equal-size gray bars as placeholders (no shimmer, to avoid layout shift) -->
      <tbody v-if="loading">
        <tr v-for="i in 4" :key="`sk-${i}`" class="border-t border-line-rule">
          <td v-for="col in columns" :key="col.key" class="px-3 py-3.5">
            <div class="h-3 rounded-full bg-raised" :style="{ width: col.width ? '60%' : '78%' }" />
          </td>
        </tr>
      </tbody>

      <!-- Empty state: keep the box and a single line of text -->
      <tbody v-else-if="empty">
        <tr>
          <td :colspan="columns.length" class="px-3 py-4">
            <div class="empty-slot">{{ emptyText ?? t('common.noData') }}</div>
          </td>
        </tr>
      </tbody>

      <tbody v-else class="border-t border-line-rule">
        <slot />
      </tbody>
    </table>
  </div>
</template>

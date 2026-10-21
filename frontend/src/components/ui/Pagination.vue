<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from './Icon.vue'

const { t } = useI18n()

const props = defineProps<{ page: number; pageSize: number; total: number }>()
const emit = defineEmits<{ change: [page: number] }>()

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))
const range = computed(() => {
  const from = props.total === 0 ? 0 : (props.page - 1) * props.pageSize + 1
  const to = Math.min(props.total, props.page * props.pageSize)
  return { from, to }
})
const pages = computed(() => {
  const list: number[] = []
  const start = Math.max(1, props.page - 2)
  const end = Math.min(totalPages.value, start + 4)
  for (let i = Math.max(1, end - 4); i <= end; i++) list.push(i)
  return list
})
</script>

<template>
  <div v-if="total > 0" class="flex items-center justify-between pt-4 text-body text-ink-muted">
    <span class="tabular-nums">{{ t('common.pageRange', { from: range.from, to: range.to, total }) }}</span>
    <div class="flex items-center gap-1">
      <button
        class="flex h-ctl w-ctl items-center justify-center rounded-ctl border border-line-control text-ink-muted outline-none
          transition-colors hover:border-accent hover:text-accent disabled:opacity-40 disabled:cursor-not-allowed"
        :disabled="page <= 1"
        :aria-label="t('a11y.prevPage')"
        @click="emit('change', page - 1)"
      >
        <Icon name="chevron-right" :size="14" class="rotate-180" />
      </button>
      <button
        v-for="p in pages"
        :key="p"
        class="h-ctl min-w-[32px] rounded-ctl border px-1.5 text-meta font-medium tabular-nums outline-none transition-colors"
        :class="
          p === page
            ? 'border-accent bg-accent text-white'
            : 'border-line-control text-ink-muted hover:border-accent hover:text-accent'
        "
        @click="emit('change', p)"
      >
        {{ p }}
      </button>
      <button
        class="flex h-ctl w-ctl items-center justify-center rounded-ctl border border-line-control text-ink-muted outline-none
          transition-colors hover:border-accent hover:text-accent disabled:opacity-40 disabled:cursor-not-allowed"
        :disabled="page >= totalPages"
        :aria-label="t('a11y.nextPage')"
        @click="emit('change', page + 1)"
      >
        <Icon name="chevron-right" :size="14" />
      </button>
    </div>
  </div>
</template>

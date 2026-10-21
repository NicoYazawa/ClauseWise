<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

export interface TimelineItem {
  title: string
  time?: string
  operator?: string
  tag?: string
  tagTone?: 'slate' | 'info' | 'warn' | 'danger' | 'success' | 'primary'
  content?: string
}

withDefaults(defineProps<{ items: TimelineItem[] }>(), {})
</script>

<template>
  <ol class="relative ml-1.5">
    <li v-for="(item, idx) in items" :key="idx" class="relative pl-6 pb-5 last:pb-0">
      <span
        v-if="idx < items.length - 1"
        class="absolute left-[5px] top-4 bottom-0 w-px bg-line"
      />
      <span class="absolute left-0 top-1.5 h-[11px] w-[11px] rounded-full border-2"
        :class="idx === 0 ? 'border-accent bg-accent-track' : 'border-line-control bg-white'"
      />
      <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span class="text-sm font-medium text-ink">{{ item.title }}</span>
        <span
          v-if="item.tag"
          class="px-1.5 py-0.5 rounded text-xs font-medium"
          :class="{
            'bg-line-rule text-ink-muted': (item.tagTone ?? 'slate') === 'slate',
            'bg-info-50 text-info-700': item.tagTone === 'info',
            'bg-warn-50 text-warn-700': item.tagTone === 'warn',
            'bg-danger-50 text-danger-700': item.tagTone === 'danger',
            'bg-success-50 text-success-700': item.tagTone === 'success',
            'bg-accent-soft text-accent': item.tagTone === 'primary',
          }"
        >{{ item.tag }}</span>
        <span class="text-xs text-ink-faint">{{ item.time }}</span>
      </div>
      <p v-if="item.operator" class="mt-0.5 text-xs text-ink-muted">{{ t('common.operatorLabel', { name: item.operator }) }}</p>
      <p v-if="item.content" class="mt-1 text-sm text-ink-muted leading-relaxed">{{ item.content }}</p>
    </li>
  </ol>
</template>

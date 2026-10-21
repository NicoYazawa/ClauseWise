<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from './Icon.vue'
import type { ClauseDiffItem, ClauseDiffKind } from '@/types'

const { t } = useI18n()

const props = defineProps<{ items: ClauseDiffItem[] }>()

const kindMeta = computed<Record<ClauseDiffKind, { label: string; cls: string }>>(() => ({
  added: { label: t('contracts.diff.pane.added'), cls: 'bg-success-50 text-success-700' },
  removed: { label: t('contracts.diff.pane.removed'), cls: 'bg-danger-50 text-danger-700' },
  modified: { label: t('contracts.diff.pane.modified'), cls: 'bg-warn-50 text-warn-700' },
  drift: { label: t('contracts.diff.pane.drift'), cls: 'bg-info-50 text-info-700' },
}))

const hasAny = computed(() => props.items.some((i) => i.oldText || i.newText))
</script>

<template>
  <div class="space-y-5">
    <p v-if="!hasAny" class="py-10 text-center text-sm text-ink-faint">{{ t('contracts.diff.pane.empty') }}</p>

    <div v-for="(item, idx) in items" :key="idx" class="card p-4">
      <div class="flex flex-wrap items-center gap-2 mb-3">
        <span class="text-sm font-semibold text-ink">{{ item.clauseNo }}</span>
        <span class="px-2 py-0.5 rounded-full text-xs font-medium" :class="kindMeta[item.kind].cls">{{ kindMeta[item.kind].label }}</span>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <div class="rounded-md border border-danger-200 bg-danger-50/60 p-3">
          <p class="mb-1.5 text-xs font-medium text-danger-700">{{ t('contracts.diff.pane.baseText') }}</p>
          <p v-if="item.oldText" class="text-sm text-ink leading-relaxed line-through decoration-danger-300/80">{{ item.oldText }}</p>
          <p v-else class="text-sm text-ink-faint italic">{{ t('contracts.diff.pane.noCounterpart') }}</p>
        </div>
        <div class="rounded-md border border-success-200 bg-success-50/60 p-3">
          <p class="mb-1.5 text-xs font-medium text-success-700">{{ t('contracts.diff.pane.targetText') }}</p>
          <p v-if="item.newText" class="text-sm text-ink leading-relaxed">{{ item.newText }}</p>
          <p v-else class="text-sm text-ink-faint italic">{{ t('contracts.diff.pane.clauseDeleted') }}</p>
        </div>
      </div>

      <div class="mt-3 flex items-start gap-2 rounded-md bg-raised border border-line p-3">
        <Icon name="sparkles" :size="15" class="mt-0.5 text-accent" />
        <div>
          <p class="text-xs font-medium text-ink-muted">{{ t('contracts.diff.pane.aiSummary') }}</p>
          <p class="mt-0.5 text-sm text-ink leading-relaxed">{{ item.summary }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

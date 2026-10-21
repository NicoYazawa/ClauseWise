<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from './Icon.vue'
import { translateData } from '@/utils/i18nData'
import type { WFNode } from '@/types'

const { t } = useI18n()

/**
 * Approval-flow visualization: nodes shown in order (start → … → end)
 * state: done = completed / current = in progress / pending = not yet reached
 */
const props = defineProps<{
  nodes: WFNode[]
  currentNodeId: string
  status?: 'running' | 'approved' | 'rejected' | 'withdrawn'
}>()

function nodeState(id: string): 'done' | 'current' | 'pending' {
  const idx = props.nodes.findIndex((n) => n.id === id)
  const cur = props.nodes.findIndex((n) => n.id === props.currentNodeId)
  if (props.status && props.status !== 'running') return 'done'
  if (idx < cur) return 'done'
  if (idx === cur) return 'current'
  return 'pending'
}

const typeIcon: Record<string, string> = {
  start: 'send',
  approval: 'users',
  condition: 'filter',
  cc: 'mail',
  end: 'check-circle',
}

const signLabel = computed<Record<string, string>>(() => ({
  or: t('status.signMode.or'),
  and: t('status.signMode.and'),
  sequence: t('status.signMode.sequence'),
}))
</script>

<template>
  <div class="overflow-x-auto pb-2">
    <div class="flex items-center min-w-max px-1 py-3">
      <template v-for="(node, idx) in nodes" :key="node.id">
        <!-- Node card -->
        <div
          class="w-40 px-3 py-2.5 rounded-lg border text-center transition-colors"
          :class="{
            'border-accent bg-accent-soft': nodeState(node.id) === 'current',
            'border-success-300 bg-success-50': nodeState(node.id) === 'done',
            'border-line bg-white': nodeState(node.id) === 'pending',
          }"
        >
          <div class="flex items-center justify-center gap-1.5">
            <Icon
              :name="typeIcon[node.type] ?? 'info'"
              :size="14"
              :class="{
                'text-accent': nodeState(node.id) === 'current',
                'text-success-600': nodeState(node.id) === 'done',
                'text-ink-faint': nodeState(node.id) === 'pending',
              }"
            />
            <span
              class="text-sm font-medium"
              :class="{
                'text-accent-ink': nodeState(node.id) === 'current',
                'text-success-800': nodeState(node.id) === 'done',
                'text-ink-muted': nodeState(node.id) === 'pending',
              }"
            >{{ translateData(node.name) }}</span>
          </div>
          <div class="mt-1 flex flex-wrap items-center justify-center gap-1">
            <span v-if="node.signMode" class="text-xs text-ink-muted">{{ signLabel[node.signMode] }}</span>
            <span v-if="node.timeoutHours" class="text-xs text-ink-faint">· {{ node.timeoutHours }}h</span>
          </div>
          <p v-if="node.assignees?.length" class="mt-0.5 text-xs text-ink-faint truncate">{{ node.assignees.join(' / ') }}</p>
          <p v-if="node.rules?.length" class="mt-0.5 text-xs text-ink-faint truncate font-mono">{{ node.rules[0].when }}</p>
        </div>
        <!-- Connector -->
        <div v-if="idx < nodes.length - 1" class="flex items-center mx-1.5">
          <Icon name="arrow-right" :size="16" class="text-line-control" />
        </div>
      </template>
    </div>
  </div>
</template>

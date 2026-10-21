<script setup lang="ts">
import BaseBadge from './BaseBadge.vue'
import type { BadgeTone } from './BaseBadge.vue'
import { contractStatusLabels, taskStatusLabels, workflowStatusLabels } from '@/utils/format'
import type { ContractStatus, ReviewTaskStatus, WorkflowStatus } from '@/types'
import { computed } from 'vue'

const props = defineProps<{ kind: 'contract' | 'task' | 'workflow'; value: string }>()

// label/color are resolved reactively via the i18n proxies in format.ts,
// so the badge updates automatically when the active locale changes.
const meta = computed<{ label: string; color: BadgeTone }>(() => {
  let entry: { label: string; color: string } | undefined
  if (props.kind === 'contract') entry = contractStatusLabels[props.value as ContractStatus]
  else if (props.kind === 'task') entry = taskStatusLabels[props.value as ReviewTaskStatus]
  else entry = workflowStatusLabels[props.value as WorkflowStatus]
  return { label: entry?.label ?? props.value, color: (entry?.color ?? 'slate') as BadgeTone }
})
</script>

<template>
  <BaseBadge :tone="meta.color" dot>{{ meta.label }}</BaseBadge>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{ value: number; status?: 'normal' | 'active' | 'done' | 'error'; showLabel?: boolean }>(), {
  status: 'normal',
})

const barCls = computed(() => {
  if (props.status === 'done') return 'bg-success-500'
  if (props.status === 'error') return 'bg-danger-500'
  if (props.status === 'active') return 'bg-accent'
  return 'bg-line-control'
})
</script>

<template>
  <div class="flex items-center gap-2 min-w-[120px]">
    <div class="flex-1 h-1.5 bg-raised rounded-full overflow-hidden">
      <div
        class="h-full rounded-full transition-[width] duration-500 ease-out"
        :class="barCls"
        :style="{ width: `${Math.min(100, Math.max(0, value))}%` }"
      />
    </div>
    <span v-if="showLabel" class="text-xs text-ink-muted tabular-nums w-9 text-right">{{ value }}%</span>
  </div>
</template>

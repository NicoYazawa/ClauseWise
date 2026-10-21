<script setup lang="ts">
import Icon from './Icon.vue'

withDefaults(
  defineProps<{
    label: string
    value: number | string
    icon?: string
    tone?: 'primary' | 'warn' | 'danger' | 'info' | 'success'
    trend?: string
    linkText?: string
  }>(),
  { tone: 'primary' },
)

const emit = defineEmits<{ action: [] }>()

/** The single accent color is reserved for "actions"; the value itself stays ink-colored, not brand-colored */
const dotCls: Record<string, string> = {
  primary: 'bg-accent',
  warn: 'bg-warn-500',
  danger: 'bg-danger-500',
  info: 'bg-info-500',
  success: 'bg-success-500',
}
</script>

<template>
  <div class="card p-5 transition-colors hover:border-line-control">
    <div class="flex items-start justify-between gap-3">
      <p class="flex min-w-0 items-center gap-1.5 text-body text-ink-muted">
        <Icon v-if="icon" :name="icon" :size="14" class="shrink-0 text-ink-faint" />
        <span class="truncate">{{ label }}</span>
      </p>
      <span class="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full" :class="dotCls[tone ?? 'primary']" />
    </div>

    <p class="mt-2 text-kpi font-medium tabular-nums text-ink">{{ value }}</p>
    <p v-if="trend" class="mt-1 text-meta text-ink-muted">{{ trend }}</p>

    <button
      v-if="linkText"
      class="mt-3 text-meta text-accent outline-none transition-colors hover:underline"
      @click="emit('action')"
    >
      {{ linkText }} →
    </button>
  </div>
</template>

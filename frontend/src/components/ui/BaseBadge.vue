<script setup lang="ts">
import { computed } from 'vue'

export type BadgeTone = 'slate' | 'info' | 'warn' | 'danger' | 'success' | 'primary'

const props = withDefaults(defineProps<{ tone?: BadgeTone; dot?: boolean; size?: 'sm' | 'md' }>(), {
  tone: 'slate',
  size: 'sm',
})

/** Status pill: pale background + same-color dark text; never placed above a title, never a saturated background with white text */
const toneCls: Record<BadgeTone, string> = {
  slate: 'pill-neutral',
  info: 'bg-info-50 text-info-700',
  warn: 'pill-warning',
  danger: 'pill-negative',
  success: 'pill-positive',
  primary: 'pill-accent',
}

const dotCls: Record<BadgeTone, string> = {
  slate: 'bg-ink-faint',
  info: 'bg-info-500',
  warn: 'bg-warn-400',
  danger: 'bg-danger-500',
  success: 'bg-success-500',
  primary: 'bg-accent',
}

const classes = computed(
  () =>
    `${toneCls[props.tone]} inline-flex items-center gap-1.5 whitespace-nowrap rounded-full font-medium ${
      props.size === 'sm' ? 'px-2 h-5 text-meta' : 'px-2.5 h-6 text-body'
    }`,
)
</script>

<template>
  <span :class="classes">
    <span v-if="dot" :class="['inline-block h-1.5 w-1.5 shrink-0 rounded-full', dotCls[tone]]" />
    <slot />
  </span>
</template>

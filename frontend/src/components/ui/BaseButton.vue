<script setup lang="ts">
import { computed } from 'vue'
import Icon from './Icon.vue'

const props = withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'success'
    size?: 'sm' | 'md'
    icon?: string
    disabled?: boolean
    loading?: boolean
    block?: boolean
  }>(),
  { variant: 'primary', size: 'md' },
)

const classes = computed(() => {
  const sizeCls = props.size === 'sm' ? 'btn-sm' : ''
  const variantCls: Record<string, string> = {
    primary: 'btn-primary',
    secondary: 'btn-secondary',
    ghost: 'btn-ghost',
    danger: 'btn-danger',
    success: 'bg-success-500 text-white hover:bg-success-700 btn',
  }
  return [variantCls[props.variant], sizeCls, props.block ? 'w-full' : '']
})
</script>

<template>
  <button :class="classes" :disabled="disabled || loading" type="button">
    <Icon v-if="loading" name="refresh" :size="size === 'sm' ? 12 : 14" class="animate-spin" />
    <Icon v-else-if="icon" :name="icon" :size="size === 'sm' ? 13 : 15" />
    <slot />
  </button>
</template>

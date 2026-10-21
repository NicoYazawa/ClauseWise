<script setup lang="ts">
import {
  SelectContent,
  SelectItem,
  SelectItemText,
  SelectPortal,
  SelectRoot,
  SelectTrigger,
  SelectValue,
  SelectViewport,
} from 'reka-ui'
import Icon from './Icon.vue'

defineProps<{
  label: string
  modelValue: string
  options: Array<{ value: string; label: string }>
  placeholder?: string
  hint?: string
}>()
defineEmits<{ 'update:modelValue': [value: string] }>()
</script>

<template>
  <div>
    <label class="label">
      {{ label }}
      <span v-if="hint" class="ml-1.5 font-normal text-meta text-ink-faint">{{ hint }}</span>
    </label>

    <SelectRoot :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event as string)">
      <SelectTrigger
        class="input flex items-center justify-between gap-2 text-left
          data-[state=open]:border-accent data-[placeholder]:text-ink-faint"
      >
        <SelectValue :placeholder="placeholder ?? ''" />
        <Icon name="chevron-down" :size="14" class="shrink-0 text-ink-faint" />
      </SelectTrigger>

      <SelectPortal>
        <SelectContent
          position="popper"
          :side-offset="4"
          class="z-[60] max-h-72 min-w-[var(--reka-select-trigger-width)] overflow-hidden rounded-card border border-line
            bg-surface p-1 shadow-float
            data-[state=open]:animate-[menu-in_140ms_cubic-bezier(0.22,1,0.36,1)]"
        >
          <SelectViewport>
            <SelectItem
              v-for="opt in options"
              :key="opt.value"
              :value="opt.value"
              class="flex h-8 cursor-pointer select-none items-center rounded-ctl px-2.5 text-body text-ink-muted outline-none
                data-[highlighted]:bg-raised data-[highlighted]:text-ink
                data-[state=checked]:font-medium data-[state=checked]:text-ink"
            >
              <SelectItemText>{{ opt.label }}</SelectItemText>
            </SelectItem>
          </SelectViewport>
        </SelectContent>
      </SelectPortal>
    </SelectRoot>
  </div>
</template>

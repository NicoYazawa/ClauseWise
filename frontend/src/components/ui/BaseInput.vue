<script setup lang="ts">
defineProps<{
  label: string
  hint?: string
  placeholder?: string
  type?: string
  modelValue: string
  disabled?: boolean
}>()
defineEmits<{ 'update:modelValue': [value: string] }>()
</script>

<template>
  <div>
    <label class="label">
      {{ label }}
      <span v-if="hint" class="ml-1.5 font-normal text-meta text-ink-faint">{{ hint }}</span>
    </label>
    <input
      class="input"
      :type="type ?? 'text'"
      :value="modelValue"
      :placeholder="placeholder"
      :disabled="disabled"
      @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
    />
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ title?: string; subtitle?: string; padding?: string }>(), { padding: 'p-5' })
</script>

<template>
  <section class="card" :class="padding">
    <div v-if="title || $slots.actions" class="mb-4 flex items-start justify-between gap-3">
      <div class="min-w-0">
        <h2 class="text-section text-ink">{{ title }}</h2>
        <p v-if="subtitle" class="mt-0.5 text-meta text-ink-muted">{{ subtitle }}</p>
      </div>
      <div v-if="$slots.actions" class="flex shrink-0 items-center gap-2">
        <slot name="actions" />
      </div>
    </div>
    <slot />
  </section>
</template>

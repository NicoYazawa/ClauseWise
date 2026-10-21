<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

defineProps<{ title: string; description?: string }>()
</script>

<template>
  <div class="mb-6">
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div class="min-w-0">
        <nav v-if="$slots.breadcrumb" class="flex items-center gap-1.5 text-meta text-ink-faint" :aria-label="t('a11y.breadcrumb')">
          <slot name="breadcrumb" />
        </nav>
        <h1 class="mt-1 text-page text-ink">{{ title }}</h1>
        <p v-if="description" class="mt-1 text-body text-ink-muted">{{ description }}</p>
      </div>
      <div class="flex shrink-0 items-center gap-2">
        <slot name="actions" />
      </div>
    </div>
  </div>
</template>

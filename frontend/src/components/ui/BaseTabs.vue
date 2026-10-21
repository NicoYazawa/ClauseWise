<script setup lang="ts">
import { TabsList, TabsRoot, TabsTrigger } from 'reka-ui'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

export interface TabItem {
  key: string
  label: string
  count?: number
}

defineProps<{ tabs: TabItem[]; modelValue: string }>()
const emit = defineEmits<{ 'update:modelValue': [key: string] }>()
</script>

<template>
  <!-- Underline tabs: sit on a 1px hairline spanning the container; the active indicator matches the tab width -->
  <TabsRoot :model-value="modelValue" @update:model-value="emit('update:modelValue', $event as string)">
    <TabsList class="flex items-center gap-1 border-b border-line" :aria-label="t('a11y.viewSwitch')">
      <TabsTrigger
        v-for="tab in tabs"
        :key="tab.key"
        :value="tab.key"
        class="group -mb-px flex items-center border-b-2 border-transparent px-3.5 py-2.5 text-body font-medium text-ink-muted
          outline-none transition-colors hover:text-ink
          data-[state=active]:border-accent data-[state=active]:text-accent-ink"
      >
        {{ tab.label }}
        <span
          v-if="tab.count !== undefined"
          class="ml-1.5 rounded-full bg-raised px-1.5 text-meta font-medium tabular-nums text-ink-muted
            group-data-[state=active]:bg-accent-soft group-data-[state=active]:text-accent-ink"
        >{{ tab.count }}</span>
      </TabsTrigger>
    </TabsList>
  </TabsRoot>
</template>

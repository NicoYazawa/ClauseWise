<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseBadge from './BaseBadge.vue'
import type { BadgeTone } from './BaseBadge.vue'
import type { FindingSource } from '@/types'

const { t } = useI18n()

const props = defineProps<{ source: FindingSource }>()

const meta = computed<{ tone: BadgeTone; label: string; desc: string }>(() =>
  props.source === 'rule'
    ? { tone: 'info', label: t('status.source.rule'), desc: t('status.sourceDesc.rule') }
    : { tone: 'primary', label: t('status.source.llm'), desc: t('status.sourceDesc.llm') },
)
</script>

<template>
  <span :title="meta.desc">
    <BaseBadge :tone="meta.tone">{{ meta.label }}</BaseBadge>
  </span>
</template>

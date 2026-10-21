<script setup lang="ts">
import { computed } from 'vue'
import BaseBadge from './BaseBadge.vue'
import type { BadgeTone } from './BaseBadge.vue'
import type { RiskLevel } from '@/types'
import { riskLevelLabels } from '@/utils/format'

const props = defineProps<{ level: RiskLevel }>()

const tone = computed<BadgeTone>(() => riskLevelLabels[props.level].color as BadgeTone)
</script>

<template>
  <BaseBadge :tone="tone" dot>{{ riskLevelLabels[level].label }}</BaseBadge>
</template>

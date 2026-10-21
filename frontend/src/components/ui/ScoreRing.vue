<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = withDefaults(defineProps<{ score: number; size?: number; label?: string }>(), {
  size: 132,
  label: '',
})

const R = 52
const CIRC = 2 * Math.PI * R

/** Color only conveys good/bad judgement, not decoration: pass uses positive, borderline uses warning, fail uses negative */
const color = computed(() => {
  if (props.score >= 85) return '#247b50'
  if (props.score >= 60) return '#b45309'
  return '#c4242a'
})

const dash = computed(() => `${(props.score / 100) * CIRC} ${CIRC}`)
const labelText = computed(() => props.label || t('review.scoreLabel'))
</script>

<template>
  <div class="relative inline-flex items-center justify-center" :style="{ width: size, height: size }">
    <!-- Thin ring: 104px diameter with 5px stroke; no label on the ring, value centered -->
    <svg :width="size" :height="size" viewBox="0 0 128 128" class="-rotate-90">
      <circle cx="64" cy="64" :r="R" fill="none" stroke="#e5e7eb" stroke-width="5" />
      <circle
        cx="64"
        cy="64"
        :r="R"
        fill="none"
        :stroke="color"
        stroke-width="5"
        stroke-linecap="round"
        :stroke-dasharray="dash"
        class="transition-[stroke-dasharray] duration-700 ease-out"
      />
    </svg>
    <div class="absolute inset-0 flex flex-col items-center justify-center">
      <span class="text-kpi font-medium tabular-nums text-ink">{{ score }}</span>
      <span class="mt-0.5 text-meta text-ink-muted">{{ labelText }}</span>
    </div>
  </div>
</template>

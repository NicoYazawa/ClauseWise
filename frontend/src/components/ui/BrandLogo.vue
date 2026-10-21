<script setup lang="ts">
/**
 * Brand mark: contract-clause text + review-passed badge.
 * Keep the shape in sync with favicon.svg (public/); update both when changing the artwork.
 */
withDefaults(defineProps<{ size?: number }>(), { size: 28 })
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 32 32" aria-hidden="true" class="shrink-0">
    <!-- Base plate: full-intensity brand color -->
    <rect x="2" y="2" width="28" height="28" rx="7" fill="rgb(var(--c-accent))" />
    <!-- Clause text: white paper surface + top-right folded corner -->
    <path
      d="M9.6 4.8h8.2L24 11v16.2a1.2 1.2 0 0 1-1.2 1.2H9.6a1.2 1.2 0 0 1-1.2-1.2V6a1.2 1.2 0 0 1 1.2-1.2Z"
      fill="#ffffff"
    />
    <path
      d="M17.8 4.8v5.9a.9.9 0 0 0 .9.9H24"
      fill="none"
      stroke="rgb(var(--c-accent))"
      stroke-width="1.7"
      stroke-linejoin="round"
    />
    <!-- Clause lines -->
    <path
      d="M11.4 14.6h7.4M11.4 18.4h4.6"
      stroke="rgb(var(--c-accent))"
      stroke-width="1.8"
      stroke-linecap="round"
    />
    <!-- Review-passed badge -->
    <circle cx="21.8" cy="21.6" r="5.4" fill="rgb(var(--c-accent))" stroke="#ffffff" stroke-width="1.7" />
    <path
      d="M19.3 21.6l1.8 1.9 3.3-3.6"
      fill="none"
      stroke="#ffffff"
      stroke-width="2.3"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
  </svg>
</template>

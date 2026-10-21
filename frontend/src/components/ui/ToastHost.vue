<script setup lang="ts">
import { computed } from 'vue'
import { AnimatePresence, motion } from 'motion-v'
import { usePreferredReducedMotion } from '@vueuse/core'
import { toastState } from '@/plugins/toast'
import Icon from './Icon.vue'

const iconMap = { success: 'check-circle', error: 'alert-triangle', info: 'info' } as const
const iconCls = {
  success: 'text-success-600',
  error: 'text-danger-500',
  info: 'text-ink-faint',
} as const

const reduced = usePreferredReducedMotion()
const spring = computed(() =>
  reduced.value === 'reduce' ? { duration: 0 } : { type: 'spring' as const, stiffness: 460, damping: 34 },
)
</script>

<template>
  <Teleport to="body">
    <div
      class="pointer-events-none fixed left-1/2 top-4 z-[70] flex w-full max-w-md -translate-x-1/2 flex-col items-center gap-2 px-4"
    >
      <AnimatePresence>
        <motion.div
          v-for="item in toastState.items"
          :key="item.id"
          :initial="{ opacity: 0, y: -12, scale: 0.98 }"
          :animate="{ opacity: 1, y: 0, scale: 1 }"
          :exit="{ opacity: 0, y: -8, scale: 0.98 }"
          :transition="spring"
          class="flex w-full items-center gap-2.5 rounded-card border border-line bg-surface px-3.5 py-2.5 text-body font-medium text-ink shadow-float"
          role="status"
        >
          <Icon :name="iconMap[item.type]" :size="16" :class="iconCls[item.type]" />
          <span class="min-w-0 flex-1">{{ item.message }}</span>
        </motion.div>
      </AnimatePresence>
    </div>
  </Teleport>
</template>

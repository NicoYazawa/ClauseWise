<script setup lang="ts">
import { computed } from 'vue'
import { AnimatePresence, motion } from 'motion-v'
import { usePreferredReducedMotion } from '@vueuse/core'
import {
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from 'reka-ui'
import { useI18n } from 'vue-i18n'
import Icon from './Icon.vue'

const { t } = useI18n()

const props = withDefaults(defineProps<{ open: boolean; title: string; width?: string }>(), { width: 'max-w-lg' })

const emit = defineEmits<{ close: [] }>()

const isOpen = computed({
  get: () => props.open,
  set: (v: boolean) => {
    if (!v) emit('close')
  },
})

/** A modal is a truly floating layer: shadows allowed; degrades to instant under the reduced-motion preference */
const reduced = usePreferredReducedMotion()
const panel = computed(() =>
  reduced.value === 'reduce' ? { duration: 0 } : { type: 'spring' as const, stiffness: 420, damping: 34 },
)
const fade = computed(() => (reduced.value === 'reduce' ? { duration: 0 } : { duration: 0.15 }))
</script>

<template>
  <DialogRoot v-model:open="isOpen">
    <DialogPortal force-mount>
      <AnimatePresence>
        <DialogOverlay v-if="isOpen" as-child>
          <motion.div
            class="fixed inset-0 z-40 bg-ink/40"
            :initial="{ opacity: 0 }"
            :animate="{ opacity: 1 }"
            :exit="{ opacity: 0 }"
            :transition="fade"
          />
        </DialogOverlay>
      </AnimatePresence>

      <AnimatePresence>
        <DialogContent v-if="isOpen" as-child>
          <motion.div
            class="pointer-events-none fixed inset-0 z-50 flex items-center justify-center p-4"
            :initial="{ opacity: 0 }"
            :animate="{ opacity: 1 }"
            :exit="{ opacity: 0 }"
            :transition="fade"
          >
            <motion.div
              class="pointer-events-auto flex max-h-[85vh] w-full flex-col overflow-hidden rounded-card border border-line bg-surface shadow-float"
              :class="width"
              :initial="{ y: 12, scale: 0.98 }"
              :animate="{ y: 0, scale: 1 }"
              :exit="{ y: 8, scale: 0.98 }"
              :transition="panel"
            >
              <div class="flex items-center justify-between gap-3 border-b border-line px-5 py-3.5">
                <DialogTitle class="text-section text-ink">{{ title }}</DialogTitle>
                <DialogDescription class="sr-only">{{ title }}</DialogDescription>
                <DialogClose
                  class="rounded-ctl p-1 text-ink-faint outline-none transition-colors hover:bg-raised hover:text-ink"
                  :aria-label="t('a11y.close')"
                >
                  <Icon name="x" :size="18" />
                </DialogClose>
              </div>

              <div class="flex-1 overflow-y-auto px-5 py-4">
                <slot />
              </div>

              <div v-if="$slots.footer" class="flex justify-end gap-2.5 border-t border-line bg-raised px-5 py-3">
                <slot name="footer" />
              </div>
            </motion.div>
          </motion.div>
        </DialogContent>
      </AnimatePresence>
    </DialogPortal>
  </DialogRoot>
</template>

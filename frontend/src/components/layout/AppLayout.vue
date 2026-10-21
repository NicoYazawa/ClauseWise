<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { motion } from 'motion-v'
import { usePreferredReducedMotion } from '@vueuse/core'
import {
  DialogClose,
  DialogContent,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from 'reka-ui'
import AppSidebar from './AppSidebar.vue'
import AppTopBar from './AppTopBar.vue'
import ToastHost from '@/components/ui/ToastHost.vue'
import Icon from '@/components/ui/Icon.vue'

const { t } = useI18n()
const route = useRoute()

/** Mobile navigation drawer: the sidebar folds into a full-screen sheet */
const navOpen = ref(false)
watch(() => route.path, () => (navOpen.value = false))

/** Route change does a single subtle float; degrades to instant under the reduced-motion preference */
const reduced = usePreferredReducedMotion()
const pageMotion = computed(() =>
  reduced.value === 'reduce'
    ? {}
    : {
        initial: { opacity: 0, y: 8 },
        animate: { opacity: 1, y: 0 },
        transition: { duration: 0.18, ease: [0.22, 1, 0.36, 1] as [number, number, number, number] },
      },
)
</script>

<template>
  <div class="flex min-h-screen flex-col bg-ground">
    <AppTopBar @open-nav="navOpen = true" />

    <div class="flex flex-1 min-h-0">
      <!-- Desktop: a 230px tabbed sidebar sharing the page background, separated only by a 1px hairline -->
      <aside class="hidden w-sidebar shrink-0 border-r border-line lg:block">
        <div class="sticky top-topbar h-[calc(100vh-var(--topbar-height))] overflow-hidden">
          <AppSidebar />
        </div>
      </aside>

      <main class="min-w-0 flex-1 p-6">
        <RouterView v-slot="{ Component, route: r }">
          <motion.div :key="r.path" v-bind="pageMotion">
            <component :is="Component" />
          </motion.div>
        </RouterView>
      </main>
    </div>

    <!-- Mobile: the sidebar folds into a drawer -->
    <DialogRoot v-model:open="navOpen">
      <DialogPortal>
        <DialogOverlay class="fixed inset-0 z-40 bg-ink/40 data-[state=open]:animate-[fade-in_140ms_ease-out]" />
        <DialogContent
          class="fixed inset-y-0 left-0 z-50 w-[86vw] max-w-sidebar border-r border-line bg-ground shadow-float outline-none
            data-[state=open]:animate-[sheet-in_220ms_cubic-bezier(0.22,1,0.36,1)]"
        >
          <DialogTitle class="sr-only">{{ t('common.menu') }}</DialogTitle>
          <DialogClose
            class="absolute right-3 top-4 z-10 rounded-ctl p-1.5 text-ink-muted transition-colors hover:bg-raised hover:text-ink"
            :aria-label="t('common.cancel')"
          >
            <Icon name="x" :size="18" />
          </DialogClose>
          <AppSidebar />
        </DialogContent>
      </DialogPortal>
    </DialogRoot>

    <ToastHost />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import GlobalSearchPanel from './GlobalSearchPanel.vue'
import BaseModal from '@/components/ui/BaseModal.vue'
import Icon from '@/components/ui/Icon.vue'

const { t } = useI18n()
const modalOpen = ref(false)
</script>

<template>
  <div class="flex items-center gap-2">
    <div class="hidden w-[300px] lg:block xl:w-[380px]">
      <GlobalSearchPanel />
    </div>

    <button
      type="button"
      class="-mr-1 rounded-ctl p-2 text-ink-muted transition-colors hover:bg-raised hover:text-ink lg:hidden"
      :aria-label="t('search.title')"
      @click="modalOpen = true"
    >
      <Icon name="search" :size="18" />
    </button>

    <BaseModal :open="modalOpen" :title="t('search.title')" width="max-w-xl" @close="modalOpen = false">
      <GlobalSearchPanel mode="block" />
    </BaseModal>
  </div>
</template>

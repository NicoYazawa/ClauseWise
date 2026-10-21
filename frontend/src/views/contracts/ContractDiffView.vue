<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { fetchVersions, fetchDiff, fetchContract } from '@/api/contracts'
import { qk } from '@/api/queryKeys'
import { useApiList, useApiDetail } from '@/composables/useApiQuery'
import type { ClauseDiffItem, Contract, ContractVersion } from '@/types'
import PageHeader from '@/components/ui/PageHeader.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import DiffPane from '@/components/ui/DiffPane.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import Icon from '@/components/ui/Icon.vue'

const { t } = useI18n()
const route = useRoute()
const contractId = Number(route.params.id)

// ===== Data layer: TanStack Query =====
// Contract and version list are fetched in parallel; the diff result is keyed by
// (contractId, base, target) and auto-refetches when the version pair changes.
const { data: contract } = useApiDetail<Contract>(
  qk.contracts.detail(contractId),
  () => fetchContract(contractId),
)
const { list: versions } = useApiList<ContractVersion>(
  qk.contracts.versions(contractId),
  () => fetchVersions(contractId),
)

const sortedVersions = computed(() => [...versions.value].sort((a, b) => a.versionNo - b.versionNo))

/** Default when the user hasn't chosen: base = lowest version, target = highest. */
const basePicked = ref<number | null>(null)
const targetPicked = ref<number | null>(null)

const baseVersion = computed({
  get: () => basePicked.value ?? sortedVersions.value[0]?.versionNo ?? 0,
  set: (v: number | string) => {
    basePicked.value = Number(v)
  },
})
const targetVersion = computed({
  get: () => targetPicked.value ?? sortedVersions.value[sortedVersions.value.length - 1]?.versionNo ?? 0,
  set: (v: number | string) => {
    targetPicked.value = Number(v)
  },
})

const canDiff = computed(
  () => baseVersion.value > 0 && targetVersion.value > 0 && baseVersion.value !== targetVersion.value,
)

const { list: items, loading, reload: reloadDiff } = useApiList<ClauseDiffItem>(
  computed(() => qk.contracts.diff(contractId, baseVersion.value, targetVersion.value)),
  () => fetchDiff(contractId, baseVersion.value, targetVersion.value),
  { enabled: canDiff },
)

/** Manual re-run (switching versions already auto re-compares). */
function runDiff() {
  reloadDiff()
}
</script>

<template>
  <div>
    <PageHeader
      :title="t('contracts.diff.title')"
      :description="`${contract?.title ?? ''} · ${t('contracts.diff.desc')}`"
    >
      <template #breadcrumb>
        <router-link to="/contracts" class="hover:text-accent">{{ t('contracts.title') }}</router-link>
        <Icon name="chevron-right" :size="12" />
        <router-link v-if="contract" :to="`/contracts/${contract.id}`" class="hover:text-accent">{{ t('contracts.detail.breadcrumb') }}</router-link>
        <Icon name="chevron-right" :size="12" />
        <span class="text-ink-muted">{{ t('contracts.diff.breadcrumbDiff') }}</span>
      </template>
      <template #actions>
        <router-link :to="`/contracts/${contractId}`">
          <BaseButton variant="secondary" icon="arrow-left">{{ t('contracts.diff.back') }}</BaseButton>
        </router-link>
      </template>
    </PageHeader>

    <!-- Version pair selection -->
    <BaseCard :title="t('contracts.diff.selectPairTitle')" :subtitle="t('contracts.diff.selectPairSubtitle')" class="mb-4">
      <div class="flex flex-wrap items-end gap-4">
        <div>
          <label class="label">{{ t('contracts.diff.baseVersion') }}</label>
          <select v-model="baseVersion" class="input cursor-pointer w-44">
            <option v-for="v in versions" :key="v.id" :value="v.versionNo">v{{ v.versionNo }} · {{ v.fileName }}</option>
          </select>
        </div>
        <Icon name="arrow-right" :size="18" class="mb-2.5 text-line-control" />
        <div>
          <label class="label">{{ t('contracts.diff.targetVersion') }}</label>
          <select v-model="targetVersion" class="input cursor-pointer w-44">
            <option v-for="v in versions" :key="v.id" :value="v.versionNo">v{{ v.versionNo }} · {{ v.fileName }}</option>
          </select>
        </div>
        <BaseButton class="mb-0.5" icon="compare" :loading="loading" @click="runDiff">{{ t('contracts.diff.start') }}</BaseButton>
      </div>
    </BaseCard>

    <!-- Diff result -->
    <div v-if="loading" class="card p-16 text-center">
      <Icon name="refresh" :size="26" class="inline-block animate-spin text-ink-faint" />
      <p class="mt-2 text-sm text-ink-faint">{{ t('contracts.diff.loading') }}</p>
    </div>
    <DiffPane v-else :items="items" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { fetchContract, fetchVersions, fetchClauses, downloadContract, uploadContractVersion } from '@/api/contracts'
import { startReview } from '@/api/reviews'
import { qk } from '@/api/queryKeys'
import { useApiList, useApiDetail, useApiMutation } from '@/composables/useApiQuery'
import type { Contract, ContractVersion, ContractClause } from '@/types'
import { contractTypeLabels, formatAmount, formatDateTime, fromNow, maskIdNo, maskPhone } from '@/utils/format'
import { toastSuccess, toastError, toastInfo } from '@/plugins/toast'
import PageHeader from '@/components/ui/PageHeader.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseBadge from '@/components/ui/BaseBadge.vue'
import StatusBadge from '@/components/ui/StatusBadge.vue'
import BaseTabs from '@/components/ui/BaseTabs.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseModal from '@/components/ui/BaseModal.vue'
import Icon from '@/components/ui/Icon.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const contractId = Number(route.params.id)

// ===== Data layer: TanStack Query =====
// Contract and version list are independent -> fetched in parallel;
// clauses depend on the selected version id -> fetched after it arrives.
const { data: contract, loading: contractLoading, reload: reloadContract } = useApiDetail<Contract>(
  qk.contracts.detail(contractId),
  () => fetchContract(contractId),
)
const { list: versions, reload: reloadVersions } = useApiList(qk.contracts.versions(contractId), () => fetchVersions(contractId))

const tab = ref('clauses')
const starting = ref(false)

/** When the user hasn't explicitly chosen, default to the latest version. */
const selectedVersionId = ref<number | null>(null)
const activeVersionId = computed(() => selectedVersionId.value ?? versions.value[0]?.id ?? 0)

const { list: clauses, loading: clausesLoading } = useApiList<ContractClause>(
  computed(() => qk.contracts.clauses(activeVersionId.value)),
  () => fetchClauses(activeVersionId.value),
  { enabled: computed(() => activeVersionId.value > 0) },
)

const loading = computed(() => contractLoading.value || clausesLoading.value)

const activeVersion = computed(() => versions.value.find((v) => v.id === activeVersionId.value) ?? versions.value[0])

// Tone is language-independent; labels come from the locale.
const channelTone: Record<string, 'info' | 'primary' | 'warn'> = { text: 'info', vision: 'primary', mixed: 'warn' }
const parseStatusTone: Record<string, 'success' | 'info' | 'danger'> = { parsed: 'success', parsing: 'info', failed: 'danger', pending: 'info' }

async function selectVersion(v: ContractVersion) {
  selectedVersionId.value = v.id
  tab.value = 'clauses'
}

async function onDownload() {
  if (!contract.value) return
  const name = await downloadContract(contract.value.id)
  toastInfo(t('contracts.toastDownload', { name }))
}

// ===== Mutation: start review =====
const startReviewMutation = useApiMutation(
  (payload: { contractId: number; taskType: 'full' | 'diff' }) => startReview(payload),
  {
    invalidate: qk.review.tasks(),
    onSuccess: (task) => {
      toastSuccess(t('contracts.detail.startReviewToast'))
      router.push(`/review/${task.id}`)
    },
    onError: (e) => toastError(e instanceof Error ? e.message : t('contracts.detail.startReviewFailed')),
  },
)

async function onStartReview() {
  if (!contract.value) return
  starting.value = true
  try {
    await startReviewMutation.mutateAsync({
      contractId: contract.value.id,
      taskType: contract.value.currentVersion > 1 ? 'diff' : 'full',
    })
  } catch (e) {
    toastError(e instanceof Error ? e.message : t('contracts.detail.startReviewFailed'))
  } finally {
    starting.value = false
  }
}

// ===== Upload a new version (version chain vN -> vN+1; old versions immutable) =====
const verUploadOpen = ref(false)
const verFile = ref<File | null>(null)
const verDragOver = ref(false)
const verUploading = ref(false)

const ACCEPT = ['.pdf', '.docx', '.jpg', '.jpeg', '.png']
const MAX_MB = 50

function validateVerFile(f: File): string | null {
  const ext = `.${f.name.split('.').pop()?.toLowerCase()}`
  if (!ACCEPT.includes(ext)) return t('contracts.errorFormat', { ext })
  if (f.size > MAX_MB * 1024 * 1024) return t('contracts.errorSize', { max: MAX_MB })
  return null
}

function pickVerFile(f: File | null) {
  if (!f) return
  const err = validateVerFile(f)
  if (err) {
    toastError(err)
    return
  }
  verFile.value = f
}

function onVerDrop(e: DragEvent) {
  verDragOver.value = false
  pickVerFile(e.dataTransfer?.files?.[0] ?? null)
}

// ===== Mutation: upload a revised version =====
const verUploadMutation = useApiMutation(
  (payload: { contractId: number; file: File }) => uploadContractVersion(payload.contractId, { file: payload.file }),
  {
    invalidate: qk.contracts.all,
    onSuccess: (updated) => {
      toastSuccess(t('contracts.detail.verUploadedToast', { no: updated.currentVersion }))
      verUploadOpen.value = false
      verFile.value = null
      tab.value = 'versions'
    },
    onError: (e) => toastError(e instanceof Error ? e.message : t('contracts.detail.verUploadFailed')),
  },
)

async function submitVerUpload() {
  if (!verFile.value || !contract.value) return
  verUploading.value = true
  try {
    await verUploadMutation.mutateAsync({ contractId: contract.value.id, file: verFile.value })
    // After parsing finishes, refresh once to show the new version's clauses & parse channel.
    setTimeout(() => {
      reloadContract()
      reloadVersions()
    }, 6000)
  } catch (e) {
    toastError(e instanceof Error ? e.message : t('contracts.detail.verUploadFailed'))
  } finally {
    verUploading.value = false
  }
}
</script>

<template>
  <div v-if="contract">
    <PageHeader :title="contract.title" :description="`${t('contracts.title')} ${contract.contractNo} · ${t('contracts.detail.infoCounterparty')} ${contract.ownerName}`">
      <template #breadcrumb>
        <router-link to="/contracts" class="hover:text-accent">{{ t('contracts.title') }}</router-link>
        <Icon name="chevron-right" :size="12" />
        <span class="text-ink-muted">{{ t('contracts.detail.breadcrumb') }}</span>
      </template>
      <template #actions>
        <BaseButton variant="secondary" icon="download" @click="onDownload">{{ t('contracts.detail.downloadOriginal') }}</BaseButton>
        <BaseButton
          v-if="['parsed', 'review_blocked', 'review_passed'].includes(contract.status)"
          icon="sparkles"
          :loading="starting"
          @click="onStartReview"
        >{{ contract.currentVersion > 1 ? t('contracts.detail.startDiff') : t('contracts.detail.startFull') }}</BaseButton>
      </template>
    </PageHeader>

    <!-- Info header card -->
    <div class="card p-5 mb-4">
      <div class="flex flex-wrap items-center gap-x-8 gap-y-4">
        <div>
          <p class="text-xs text-ink-faint">{{ t('contracts.detail.infoType') }}</p>
          <p class="mt-1 text-sm font-medium text-ink">{{ contractTypeLabels[contract.contractType] }}</p>
        </div>
        <div>
          <p class="text-xs text-ink-faint">{{ t('contracts.detail.infoStatus') }}</p>
          <p class="mt-1"><StatusBadge kind="contract" :value="contract.status" /></p>
        </div>
        <div>
          <p class="text-xs text-ink-faint">{{ t('contracts.detail.infoVersion') }}</p>
          <p class="mt-1 text-sm font-medium text-ink font-mono">v{{ contract.currentVersion }}</p>
        </div>
        <div>
          <p class="text-xs text-ink-faint">{{ t('contracts.detail.infoAmount') }}</p>
          <p class="mt-1 text-sm font-medium text-ink tabular-nums">{{ contract.amount > 0 ? formatAmount(contract.amount) : '—' }}</p>
        </div>
        <div>
          <p class="text-xs text-ink-faint">{{ t('contracts.detail.infoCounterparty') }}</p>
          <p class="mt-1 text-sm font-medium text-ink">{{ contract.counterparty.name }}</p>
          <p class="mt-0.5 text-xs text-ink-faint font-mono">{{ maskIdNo(contract.counterparty.idNo) }} · {{ maskPhone(contract.counterparty.phone) }}</p>
        </div>
        <div>
          <p class="text-xs text-ink-faint">{{ t('contracts.detail.infoCreated') }}</p>
          <p class="mt-1 text-sm text-ink-muted">{{ formatDateTime(contract.createdAt) }}</p>
          <p class="mt-0.5 text-xs text-ink-faint">{{ fromNow(contract.updatedAt) }} {{ t('contracts.detail.updatedSuffix') }}</p>
        </div>
      </div>
    </div>

    <div class="card">
      <BaseTabs
        v-model="tab"
        :tabs="[
          { key: 'clauses', label: t('contracts.detail.tabClauses'), count: clauses.length },
          { key: 'versions', label: t('contracts.detail.tabVersions'), count: versions.length },
        ]"
      />

      <!-- Structured clauses -->
      <div v-if="tab === 'clauses'" class="p-4">
        <p v-if="activeVersion" class="mb-3 text-xs text-ink-faint">
          {{ t('contracts.detail.showVersion', { name: activeVersion.fileName, no: activeVersion.versionNo, channel: t(`status.channel.${activeVersion.parseChannel ?? 'text'}`) || t('contracts.detail.channelPending') }) }}
        </p>
        <div v-if="clauses.length === 0" class="py-14 text-center text-sm text-ink-faint">{{ t('contracts.detail.noClauses') }}</div>
        <div v-else class="space-y-2.5">
          <div v-for="cl in clauses" :key="cl.id" class="rounded-lg border border-line p-4 hover:border-accent-track transition-colors">
            <div class="flex flex-wrap items-center gap-2">
              <span class="px-2 py-0.5 rounded bg-line-rule text-xs font-semibold text-ink-muted font-mono">{{ cl.clauseNo }}</span>
              <BaseBadge tone="primary">{{ cl.clauseType }}</BaseBadge>
              <span class="ml-auto text-xs text-ink-faint">{{ t('contracts.detail.pageNo', { n: cl.pageNo }) }}</span>
            </div>
            <p class="mt-2.5 text-sm text-ink leading-relaxed">{{ cl.content }}</p>
          </div>
        </div>
      </div>

      <!-- Version history -->
      <div v-if="tab === 'versions'" class="p-4">
        <div class="mb-4 flex flex-wrap justify-end gap-2">
          <BaseButton icon="upload" size="sm" @click="verUploadOpen = true">{{ t('contracts.detail.uploadNewVersion') }}</BaseButton>
          <BaseButton
            v-if="versions.length >= 2"
            variant="secondary"
            size="sm"
            icon="compare"
            @click="router.push(`/contracts/${contract.id}/diff`)"
          >{{ t('contracts.detail.versionDiff') }}</BaseButton>
        </div>
        <div class="space-y-3">
          <div
            v-for="(v, idx) in versions"
            :key="v.id"
            class="flex items-center gap-4 rounded-lg border p-4 cursor-pointer transition-colors"
            :class="v.id === activeVersionId ? 'border-accent bg-accent-soft/40' : 'border-line hover:border-accent-track'"
            @click="selectVersion(v)"
          >
            <span class="flex h-9 w-9 items-center justify-center rounded-full text-xs font-bold font-mono"
              :class="idx === 0 ? 'bg-accent-track text-accent' : 'bg-line-rule text-ink-muted'"
            >v{{ v.versionNo }}</span>
            <div class="min-w-0 flex-1">
              <p class="text-sm font-medium text-ink truncate">{{ v.fileName }}</p>
              <p class="mt-0.5 text-xs text-ink-faint">{{ (v.fileSizeKb / 1024).toFixed(1) }} MB · {{ formatDateTime(v.createdAt) }}<span v-if="v.parentId"> · {{ t('contracts.detail.revisedFrom', { n: versions.find((x) => x.id === v.parentId)?.versionNo }) }}</span></p>
            </div>
            <BaseBadge v-if="v.parseChannel" :tone="channelTone[v.parseChannel]">{{ t(`status.channel.${v.parseChannel}`) }}</BaseBadge>
            <BaseBadge :tone="parseStatusTone[v.parseStatus]">{{ t(`status.parseStatus.${v.parseStatus}`) }}</BaseBadge>
            <Icon v-if="v.id === activeVersionId" name="check-circle" :size="16" class="text-accent" />
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Upload new version modal -->
  <BaseModal v-if="contract" v-model:open="verUploadOpen" :title="t('contracts.detail.verModalTitle')" width="max-w-lg" @close="verUploadOpen = false; verFile = null">
    <div class="space-y-4">
      <div class="rounded-md bg-accent-soft/60 border border-accent-track px-3.5 py-2.5 text-xs text-ink-muted leading-relaxed">
        {{ t('contracts.detail.verNote', { from: contract.currentVersion, to: contract.currentVersion + 1 }) }}
      </div>
      <div
        class="border-2 border-dashed rounded-lg p-7 text-center transition-colors cursor-pointer"
        :class="verDragOver ? 'border-accent bg-accent-soft' : 'border-line-control hover:border-accent'"
        @dragover.prevent="verDragOver = true"
        @dragleave="verDragOver = false"
        @drop.prevent="onVerDrop"
        @click="($refs.verFileInput as HTMLInputElement).click()"
      >
        <input ref="verFileInput" type="file" class="hidden" accept=".pdf,.docx,.jpg,.jpeg,.png" @change="pickVerFile(($event.target as HTMLInputElement).files?.[0] ?? null)" />
        <template v-if="!verFile">
          <Icon name="upload" :size="28" class="mx-auto text-line-control" />
          <p class="mt-3 text-sm font-medium text-ink-muted">{{ t('contracts.detail.dropHint') }}</p>
          <p class="mt-1 text-xs text-ink-faint">{{ t('contracts.detail.dropFormats') }}</p>
        </template>
        <template v-else>
          <Icon name="file-text" :size="28" class="mx-auto text-accent" />
          <p class="mt-3 text-sm font-medium text-ink">{{ verFile.name }}</p>
          <p class="mt-1 text-xs text-ink-faint">{{ (verFile.size / 1024).toFixed(0) }} KB · {{ t('contracts.detail.fileRechoose') }}</p>
        </template>
      </div>
      <div class="rounded-md bg-raised border border-line p-3 text-xs text-ink-muted leading-relaxed">
        <p class="flex items-center gap-1.5 font-medium text-ink-muted"><Icon name="info" :size="13" /> {{ t('contracts.detail.parseNoteTitle') }}</p>
        <p class="mt-1.5">{{ t('contracts.detail.parseNote') }}</p>
      </div>
    </div>
    <template #footer>
      <BaseButton variant="secondary" @click="verUploadOpen = false">{{ t('common.cancel') }}</BaseButton>
      <BaseButton icon="upload" :loading="verUploading" :disabled="!verFile" @click="submitVerUpload">{{ verUploading ? t('contracts.detail.uploading') : t('contracts.uploadAndParse') }}</BaseButton>
    </template>
  </BaseModal>

  <!-- Loading -->
  <div v-else class="py-24 text-center">
    <Icon name="refresh" :size="26" class="inline-block animate-spin text-ink-faint" />
  </div>
</template>

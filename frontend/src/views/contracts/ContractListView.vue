<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { fetchContracts, uploadContract, retryParse, archiveContract, downloadContract, type ContractQuery } from '@/api/contracts'
import { qk } from '@/api/queryKeys'
import { useApiList, useApiMutation } from '@/composables/useApiQuery'
import type { Contract, ContractType } from '@/types'
import { contractTypeLabels, contractStatusLabels, formatAmount, formatDateTime } from '@/utils/format'
import { toastSuccess, toastError, toastInfo } from '@/plugins/toast'
import PageHeader from '@/components/ui/PageHeader.vue'
import BaseTable from '@/components/ui/BaseTable.vue'
import BaseBadge from '@/components/ui/BaseBadge.vue'
import StatusBadge from '@/components/ui/StatusBadge.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseInput from '@/components/ui/BaseInput.vue'
import BaseSelect from '@/components/ui/BaseSelect.vue'
import Pagination from '@/components/ui/Pagination.vue'
import Icon from '@/components/ui/Icon.vue'

const { t } = useI18n()
const router = useRouter()
const route = useRoute()

// Separate the input conditions from the applied ones: submit only on search/enter,
// so typing does not trigger a request on every keystroke.
// The initial keyword may come from the top-bar global search (?q=...).
const initialKeyword = String(route.query.q ?? '').trim()
const query = ref<ContractQuery>({ keyword: initialKeyword, contractType: '', status: '' })
const applied = ref<ContractQuery>({ keyword: initialKeyword, contractType: '', status: '' })

const { list, loading } = useApiList<Contract>(
  computed(() => qk.contracts.list(applied.value)),
  () => fetchContracts(applied.value),
)

const page = ref(1)
const pageSize = 8

const paged = computed(() => list.value.slice((page.value - 1) * pageSize, page.value * pageSize))

function onSearch() {
  applied.value = { ...query.value }
  page.value = 1
}

// Reactive option lists: labels re-resolve when the locale changes.
const typeOptions = computed(() =>
  (Object.keys(contractTypeLabels) as ContractType[]).map((v) => ({ value: v, label: contractTypeLabels[v] })),
)
const statusOptions = computed(() =>
  Object.entries(contractStatusLabels).map(([v, m]) => ({ value: v, label: m.label })),
)

// ===== Upload modal =====
const uploadOpen = ref(false)
const file = ref<File | null>(null)
const dragOver = ref(false)
const form = ref({ title: '', contractType: 'purchase', counterpartyName: '', amount: 0, amountText: '' })

const ACCEPT = ['.pdf', '.docx', '.jpg', '.jpeg', '.png']
const MAX_MB = 50

function validateFile(f: File): string | null {
  const ext = `.${f.name.split('.').pop()?.toLowerCase()}`
  if (!ACCEPT.includes(ext)) return t('contracts.errorFormat', { ext })
  if (f.size > MAX_MB * 1024 * 1024) return t('contracts.errorSize', { max: MAX_MB })
  return null
}

function pickFile(f: File | null) {
  if (!f) return
  const err = validateFile(f)
  if (err) {
    toastError(err)
    return
  }
  file.value = f
  if (!form.value.title) form.value.title = f.name.replace(/\.[^.]+$/, '')
}

function onDrop(e: DragEvent) {
  dragOver.value = false
  pickFile(e.dataTransfer?.files?.[0] ?? null)
}

// ===== TanStack Query mutations =====
const uploadMutation = useApiMutation(uploadContract, {
  invalidate: qk.contracts.all,
  onSuccess: (ct) => {
    toastSuccess(t('contracts.toastUploaded', { no: ct.contractNo }))
    uploadOpen.value = false
    resetForm()
  },
  onError: (e) => toastError(e instanceof Error ? e.message : t('contracts.errorUploadFailed')),
})

const retryMutation = useApiMutation((c: Contract) => retryParse(c.id), {
  invalidate: qk.contracts.all,
  onSuccess: (c) => {
    toastSuccess(t('contracts.toastReparse', { no: c.contractNo }))
  },
  onError: (e) => toastError(e instanceof Error ? e.message : t('contracts.errorReparseFailed')),
})

const archiveMutation = useApiMutation((c: Contract) => archiveContract(c.id), {
  invalidate: qk.contracts.all,
  onSuccess: (c) => {
    toastSuccess(t('contracts.toastArchive', { no: c.contractNo }))
  },
  onError: (e) => toastError(e instanceof Error ? e.message : t('contracts.errorArchiveFailed')),
})

const uploading = computed(() => uploadMutation.isPending.value)

function submitUpload() {
  if (!file.value) {
    toastError(t('contracts.errorPickFile'))
    return
  }
  if (!form.value.title || !form.value.counterpartyName) {
    toastError(t('contracts.errorFields'))
    return
  }
  uploadMutation.mutate({
    file: file.value,
    title: form.value.title,
    contractType: form.value.contractType as ContractType,
    counterpartyName: form.value.counterpartyName,
    amount: Number(form.value.amountText) || 0,
  })
}

function resetForm() {
  file.value = null
  form.value = { title: '', contractType: 'purchase', counterpartyName: '', amount: 0, amountText: '' }
}

async function onDownload(c: Contract) {
  try {
    const name = await downloadContract(c.id)
    toastInfo(t('contracts.toastDownload', { name }))
  } catch (e) {
    toastError(e instanceof Error ? e.message : t('contracts.errorDownloadFailed'))
  }
}

function onRetry(c: Contract) {
  retryMutation.mutate(c)
}

function onArchive(c: Contract) {
  archiveMutation.mutate(c)
}
</script>

<template>
  <div>
    <PageHeader :title="t('contracts.title')" :description="t('contracts.description')">
      <template #actions>
        <BaseButton icon="upload" @click="uploadOpen = true">{{ t('contracts.upload') }}</BaseButton>
      </template>
    </PageHeader>

    <!-- Filter bar -->
    <div class="card p-4 mb-4 flex flex-col md:flex-row md:items-center gap-3">
      <div class="relative md:flex-1">
        <Icon name="search" :size="15" class="absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" />
        <input
          v-model="query.keyword"
          class="input pl-9"
          :placeholder="t('contracts.searchPlaceholder')"
          @keyup.enter="onSearch"
        />
      </div>
      <select v-model="query.contractType" class="input cursor-pointer md:w-44 shrink-0" @change="onSearch">
        <option value="">{{ t('contracts.allTypes') }}</option>
        <option v-for="o in typeOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
      </select>
      <select v-model="query.status" class="input cursor-pointer md:w-40 shrink-0" @change="onSearch">
        <option value="">{{ t('contracts.allStatus') }}</option>
        <option v-for="o in statusOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
      </select>
      <BaseButton variant="secondary" icon="search" class="shrink-0 whitespace-nowrap" @click="onSearch">{{ t('contracts.search') }}</BaseButton>
    </div>

    <!-- Contract table -->
    <div class="card">
      <BaseTable
        :columns="[
          { key: 'title', label: t('contracts.colTitle') },
          { key: 'type', label: t('contracts.colType'), width: '100px', align: 'center' },
          { key: 'amount', label: t('contracts.colAmount'), width: '120px', align: 'center' },
          { key: 'version', label: t('contracts.colVersion'), width: '70px', align: 'center' },
          { key: 'status', label: t('contracts.colStatus'), width: '120px', align: 'center' },
          { key: 'updatedAt', label: t('contracts.colUpdated'), width: '140px', align: 'center' },
          { key: 'actions', label: t('contracts.colActions'), width: '210px' },
        ]"
        :loading="loading"
        :empty="list.length === 0"
        :empty-text="t('contracts.empty')"
      >
        <tr v-for="c in paged" :key="c.id" class="hover:bg-raised">
          <td class="table-td">
            <router-link :to="`/contracts/${c.id}`" class="font-medium text-ink hover:text-accent">{{ c.title }}</router-link>
            <p class="mt-0.5 text-xs text-ink-faint font-mono">{{ c.contractNo }} · {{ c.counterparty.name }}</p>
          </td>
          <td class="table-td">
            <BaseBadge tone="slate">{{ contractTypeLabels[c.contractType] }}</BaseBadge>
          </td>
          <td class="table-td text-center tabular-nums">{{ c.amount > 0 ? formatAmount(c.amount) : '—' }}</td>
          <td class="table-td text-center"><span class="font-mono text-ink-muted">v{{ c.currentVersion }}</span></td>
          <td class="table-td"><StatusBadge kind="contract" :value="c.status" /></td>
          <td class="table-td text-ink-muted">{{ formatDateTime(c.updatedAt) }}</td>
          <td class="table-td">
            <div class="flex items-center gap-1">
              <button class="p-1.5 rounded-md text-ink-faint hover:bg-accent-soft hover:text-accent" :title="t('contracts.viewDetail')" @click="router.push(`/contracts/${c.id}`)">
                <Icon name="eye" :size="15" />
              </button>
              <button class="p-1.5 rounded-md text-ink-faint hover:bg-accent-soft hover:text-accent" :title="t('contracts.download')" @click="onDownload(c)">
                <Icon name="download" :size="15" />
              </button>
              <button
                v-if="c.status === 'parse_failed'"
                class="p-1.5 rounded-md text-danger-500 hover:bg-danger-50" :title="t('contracts.retryParse')"
                @click="onRetry(c)"
              >
                <Icon name="refresh" :size="15" />
              </button>
              <button
                v-if="['approved', 'rejected'].includes(c.status)"
                class="p-1.5 rounded-md text-ink-faint hover:bg-warn-50 hover:text-warn-600" :title="t('contracts.archive')"
                @click="onArchive(c)"
              >
                <Icon name="archive" :size="15" />
              </button>
            </div>
          </td>
        </tr>
      </BaseTable>
      <div class="px-4 pb-3">
        <Pagination :page="page" :page-size="pageSize" :total="list.length" @change="page = $event" />
      </div>
    </div>

    <!-- Upload modal -->
    <BaseModal v-model:open="uploadOpen" :title="t('contracts.uploadTitle')" width="max-w-xl" @close="uploadOpen = false">
      <div class="space-y-4">
        <div
          class="border-2 border-dashed rounded-lg p-8 text-center transition-colors cursor-pointer"
          :class="dragOver ? 'border-accent bg-accent-soft' : 'border-line-control hover:border-accent'"
          @dragover.prevent="dragOver = true"
          @dragleave="dragOver = false"
          @drop.prevent="onDrop"
          @click="($refs.fileInput as HTMLInputElement).click()"
        >
          <input ref="fileInput" type="file" class="hidden" accept=".pdf,.docx,.jpg,.jpeg,.png" @change="pickFile(($event.target as HTMLInputElement).files?.[0] ?? null)" />
          <template v-if="!file">
            <Icon name="upload" :size="30" class="mx-auto text-line-control" />
            <p class="mt-3 text-sm font-medium text-ink-muted">{{ t('contracts.dropHint') }}</p>
            <p class="mt-1 text-xs text-ink-faint">{{ t('contracts.dropFormats') }}</p>
          </template>
          <template v-else>
            <Icon name="file-text" :size="30" class="mx-auto text-accent" />
            <p class="mt-3 text-sm font-medium text-ink">{{ file.name }}</p>
            <p class="mt-1 text-xs text-ink-faint">{{ (file.size / 1024).toFixed(0) }} KB · {{ t('contracts.fileRechoose') }}</p>
          </template>
        </div>

        <BaseInput v-model="form.title" :label="t('contracts.fieldTitle')" :placeholder="t('contracts.titlePlaceholder')" />
        <div class="grid grid-cols-2 gap-3">
          <BaseSelect v-model="form.contractType" :label="t('contracts.fieldType')" :options="typeOptions" />
          <BaseInput v-model="form.amountText" :label="t('contracts.fieldAmount')" :placeholder="t('contracts.amountPlaceholder')" />
        </div>
        <BaseInput v-model="form.counterpartyName" :label="t('contracts.fieldCounterparty')" :placeholder="t('contracts.counterpartyPlaceholder')" />

        <div class="rounded-md bg-raised border border-line p-3 text-xs text-ink-muted leading-relaxed">
          <p class="flex items-center gap-1.5 font-medium text-ink-muted"><Icon name="info" :size="13" /> {{ t('contracts.parseNoteTitle') }}</p>
          <p class="mt-1.5">{{ t('contracts.parseNote') }}</p>
        </div>
      </div>

      <template #footer>
        <BaseButton variant="secondary" @click="uploadOpen = false">{{ t('common.cancel') }}</BaseButton>
        <BaseButton icon="upload" :loading="uploading" @click="submitUpload">{{ uploading ? t('contracts.uploading') : t('contracts.uploadAndParse') }}</BaseButton>
      </template>
    </BaseModal>
  </div>
</template>

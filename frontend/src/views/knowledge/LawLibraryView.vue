<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { fetchLaws, saveLaw, markExpired, importLaws } from '@/api/knowledge'
import { qk } from '@/api/queryKeys'
import { useApiList, useApiMutation } from '@/composables/useApiQuery'
import type { LawRegulation } from '@/types'
import { formatDate } from '@/utils/format'
import { toastSuccess, toastError, toastInfo } from '@/plugins/toast'
import PageHeader from '@/components/ui/PageHeader.vue'
import BaseTable from '@/components/ui/BaseTable.vue'
import BaseBadge from '@/components/ui/BaseBadge.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseInput from '@/components/ui/BaseInput.vue'
import BaseSelect from '@/components/ui/BaseSelect.vue'
import BaseDrawer from '@/components/ui/BaseDrawer.vue'
import Pagination from '@/components/ui/Pagination.vue'
import Icon from '@/components/ui/Icon.vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const route = useRoute()

// ===== Data layer: TanStack Query =====
const { list: laws, loading } = useApiList(qk.knowledge.laws(), () => fetchLaws())

// Initial keyword may come from the top-bar global search (?q=...)
const keyword = ref(String(route.query.q ?? '').trim())
const typeFilter = ref('')
const page = ref(1)
const pageSize = 10

const filtered = computed(() =>
  laws.value.filter((l) => {
    if (typeFilter.value && l.docType !== typeFilter.value) return false
    if (keyword.value) {
      const kw = keyword.value.trim().toLowerCase()
      return l.title.toLowerCase().includes(kw) || l.content.toLowerCase().includes(kw)
    }
    return true
  }),
)
const paged = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))

function search() {
  page.value = 1
}

// ===== Detail drawer =====
const detail = ref<LawRegulation | null>(null)

// ===== Create/edit =====
const editOpen = ref(false)
const editing = ref<LawRegulation | null>(null)
const form = ref({ docType: 'law', title: '', content: '', sourceRef: '', effectiveDate: '' })
const saving = ref(false)

// ===== Mutation: save law =====
const saveMutation = useApiMutation(
  (payload: Parameters<typeof saveLaw>[0]) => saveLaw(payload),
  {
    invalidate: qk.knowledge.laws(),
    onSuccess: (_data, payload) => {
      toastSuccess(payload.id ? t('knowledge.laws.toastUpdated') : t('knowledge.laws.toastCreated'))
    },
    onError: (e) => toastError(e instanceof Error ? e.message : t('common.saveFailed')),
  },
)

function openCreate() {
  editing.value = null
  form.value = { docType: 'law', title: '', content: '', sourceRef: '', effectiveDate: new Date().toISOString().slice(0, 10) }
  editOpen.value = true
}

function openEdit(l: LawRegulation) {
  editing.value = l
  form.value = { docType: l.docType, title: l.title, content: l.content, sourceRef: l.sourceRef, effectiveDate: l.effectiveDate }
  editOpen.value = true
}

async function submitSave() {
  if (!form.value.title || !form.value.content) {
    toastError(t('knowledge.laws.fieldsRequired'))
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      await saveMutation.mutateAsync({
        id: editing.value.id,
        docType: form.value.docType as LawRegulation['docType'],
        title: form.value.title,
        content: form.value.content,
        sourceRef: form.value.sourceRef,
        effectiveDate: form.value.effectiveDate,
        expiryDate: editing.value.expiryDate,
        status: editing.value.status,
      })
    } else {
      await saveMutation.mutateAsync({
        docType: form.value.docType as LawRegulation['docType'],
        title: form.value.title,
        content: form.value.content,
        sourceRef: form.value.sourceRef,
        effectiveDate: form.value.effectiveDate,
        expiryDate: null,
        status: 'active',
      })
    }
    editOpen.value = false
  } catch (e) {
    toastError(e instanceof Error ? e.message : t('common.saveFailed'))
  } finally {
    saving.value = false
  }
}

// ===== Mutation: mark as expired =====
const expireMutation = useApiMutation((id: number) => markExpired(id), {
  invalidate: qk.knowledge.laws(),
  onSuccess: (_data, id) => {
    const l = laws.value.find((x) => x.id === id)
    toastSuccess(t('knowledge.laws.toastExpired', { title: l?.title ?? id }))
  },
  onError: (e) => toastError(e instanceof Error ? e.message : t('common.operateFailed')),
})

async function onMarkExpired(l: LawRegulation) {
  try {
    await expireMutation.mutateAsync(l.id)
  } catch {
    /* 错误已由 mutation 的 onError 统一提示，这里仅避免未处理的 Promise 拒绝 */
  }
}

// ===== Excel batch import =====
const importOpen = ref(false)
const importFile = ref<File | null>(null)
const importing = ref(false)
const importResult = ref<{ imported: number; vectorized: number } | null>(null)

function pickImportFile(f: File | null) {
  if (!f) return
  const ext = `.${f.name.split('.').pop()?.toLowerCase()}`
  if (!['.xlsx', '.xls', '.csv'].includes(ext)) {
    toastError(t('knowledge.laws.toastFormat', { ext }))
    return
  }
  importFile.value = f
  importResult.value = null
}

const importMutation = useApiMutation((file: File) => importLaws(file), {
  invalidate: qk.knowledge.laws(),
  onSuccess: (result) => {
    importResult.value = result
    toastSuccess(
      t('knowledge.laws.toastImportDone', { imported: result.imported, vectorized: result.vectorized }),
    )
  },
  onError: (e) => toastError(e instanceof Error ? e.message : t('knowledge.laws.importFailed')),
})

async function submitImport() {
  if (!importFile.value) {
    toastError(t('knowledge.laws.toastPickFile'))
    return
  }
  importing.value = true
  try {
    await importMutation.mutateAsync(importFile.value)
  } catch (e) {
    toastError(e instanceof Error ? e.message : t('knowledge.laws.importFailed'))
  } finally {
    importing.value = false
  }
}
</script>

<template>
  <div>
    <PageHeader
      :title="t('knowledge.laws.title')"
      :description="t('knowledge.laws.description')"
    >
      <template #actions>
        <BaseButton variant="secondary" icon="download" @click="importOpen = true">{{ t('knowledge.laws.bulkImport') }}</BaseButton>
        <BaseButton icon="plus" @click="openCreate">{{ t('knowledge.laws.create') }}</BaseButton>
      </template>
    </PageHeader>

    <div class="card p-4 mb-4 grid grid-cols-1 md:grid-cols-3 gap-3">
      <div class="relative md:col-span-2">
        <Icon name="search" :size="15" class="absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" />
        <input v-model="keyword" class="input pl-9" :placeholder="t('knowledge.laws.searchPlaceholder')" @keyup.enter="search" />
      </div>
      <select v-model="typeFilter" class="input cursor-pointer" @change="search">
        <option value="">{{ t('knowledge.laws.allTypes') }}</option>
        <option value="law">{{ t('knowledge.laws.typeLaw') }}</option>
        <option value="case">{{ t('knowledge.laws.typeCase') }}</option>
      </select>
    </div>

    <div class="card">
      <BaseTable
        :columns="[
          { key: 'title', label: t('knowledge.laws.colRef') },
          { key: 'docType', label: t('common.type'), width: '90px' },
          { key: 'source', label: t('common.source'), width: '180px' },
          { key: 'effective', label: t('knowledge.laws.colEffective'), width: '110px' },
          { key: 'status', label: t('common.status'), width: '90px' },
          { key: 'vector', label: t('knowledge.laws.colVector'), width: '90px' },
          { key: 'hit', label: t('knowledge.laws.colHit'), width: '70px', align: 'right' },
          { key: 'actions', label: t('common.actions'), width: '130px' },
        ]"
        :loading="loading"
        :empty="filtered.length === 0"
        :empty-text="t('knowledge.laws.empty')"
      >
        <tr v-for="l in paged" :key="l.id" class="hover:bg-raised">
          <td class="table-td">
            <button class="font-medium text-ink hover:text-accent text-left" @click="detail = l">{{ l.title }}</button>
            <p class="mt-0.5 text-xs text-ink-faint line-clamp-1 max-w-[380px]">{{ l.content }}</p>
          </td>
          <td class="table-td"><BaseBadge :tone="l.docType === 'law' ? 'primary' : 'info'">{{ l.docType === 'law' ? t('knowledge.laws.typeLaw') : t('knowledge.laws.typeCaseShort') }}</BaseBadge></td>
          <td class="table-td text-xs text-ink-muted">{{ l.sourceRef }}</td>
          <td class="table-td text-xs text-ink-muted">{{ formatDate(l.effectiveDate) }}</td>
          <td class="table-td">
            <BaseBadge :tone="l.status === 'active' ? 'success' : 'slate'">{{ l.status === 'active' ? t('knowledge.laws.active') : t('knowledge.laws.expired') }}</BaseBadge>
          </td>
          <td class="table-td">
            <span v-if="l.vectorized" class="inline-flex items-center gap-1 text-xs text-success-600"><Icon name="check-circle" :size="12" />{{ t('knowledge.laws.vectorized') }}</span>
            <span v-else class="inline-flex items-center gap-1 text-xs text-warn-600"><Icon name="refresh" :size="12" class="animate-spin" />{{ t('knowledge.laws.vectorizing') }}</span>
          </td>
          <td class="table-td text-right tabular-nums text-ink-muted">{{ l.hitCount }}</td>
          <td class="table-td">
            <div class="flex gap-1">
              <button class="p-1.5 rounded-md text-ink-faint hover:bg-accent-soft hover:text-accent" :title="t('common.edit')" @click="openEdit(l)">
                <Icon name="edit" :size="14" />
              </button>
              <button
                v-if="l.status === 'active'"
                class="p-1.5 rounded-md text-ink-faint hover:bg-warn-50 hover:text-warn-600" :title="t('knowledge.laws.markExpired')"
                @click="onMarkExpired(l)"
              >
                <Icon name="ban" :size="14" />
              </button>
            </div>
          </td>
        </tr>
      </BaseTable>
      <div class="px-4 pb-3">
        <Pagination :page="page" :page-size="pageSize" :total="filtered.length" @change="page = $event" />
      </div>
    </div>

    <!-- Detail drawer -->
    <BaseDrawer :open="!!detail" :title="detail?.title ?? ''" @close="detail = null">
      <div v-if="detail" class="space-y-4">
        <div class="flex flex-wrap gap-2">
          <BaseBadge :tone="detail.docType === 'law' ? 'primary' : 'info'">{{ detail.docType === 'law' ? t('knowledge.laws.typeLaw') : t('knowledge.laws.typeCase') }}</BaseBadge>
          <BaseBadge :tone="detail.status === 'active' ? 'success' : 'slate'">{{ detail.status === 'active' ? t('knowledge.laws.active') : t('knowledge.laws.expired') }}</BaseBadge>
          <BaseBadge tone="slate">{{ t('knowledge.laws.hitTimes', { n: detail.hitCount }) }}</BaseBadge>
        </div>
        <div class="rounded-lg border border-line bg-raised p-4">
          <p class="text-xs font-medium text-ink-faint mb-2">{{ t('knowledge.laws.contentLabel') }}</p>
          <p class="text-sm text-ink leading-relaxed">{{ detail.content }}</p>
        </div>
        <div class="grid grid-cols-2 gap-3 text-sm">
          <div><p class="text-xs text-ink-faint">{{ t('common.source') }}</p><p class="mt-1 text-ink">{{ detail.sourceRef }}</p></div>
          <div><p class="text-xs text-ink-faint">{{ t('knowledge.laws.colEffective') }}</p><p class="mt-1 text-ink">{{ formatDate(detail.effectiveDate) }}</p></div>
          <div><p class="text-xs text-ink-faint">{{ t('knowledge.laws.expiryDateLabel') }}</p><p class="mt-1 text-ink">{{ detail.expiryDate ? formatDate(detail.expiryDate) : '—' }}</p></div>
          <div><p class="text-xs text-ink-faint">{{ t('knowledge.laws.colVector') }}</p><p class="mt-1 text-ink">{{ detail.vectorized ? t('knowledge.laws.vectorizedDetail') : t('knowledge.laws.vectorizingDetail') }}</p></div>
        </div>
        <p class="text-xs text-ink-faint leading-relaxed">
          {{ t('knowledge.laws.note') }}
        </p>
      </div>
    </BaseDrawer>

    <!-- Create/edit modal -->
    <BaseModal v-model:open="editOpen" :title="editing ? t('knowledge.laws.editTitle') : t('knowledge.laws.createTitle')" width="max-w-xl" @close="editOpen = false">
      <div class="space-y-4">
        <BaseSelect
          v-model="form.docType"
          :label="t('knowledge.laws.fieldDocType')"
          :options="[
            { value: 'law', label: t('knowledge.laws.typeLaw') },
            { value: 'case', label: t('knowledge.laws.typeCase') },
          ]"
        />
        <BaseInput v-model="form.title" :label="t('knowledge.laws.fieldRef')" :placeholder="t('knowledge.laws.refPlaceholder')" />
        <div>
          <label class="label">{{ t('knowledge.laws.fieldContent') }}</label>
          <textarea v-model="form.content" rows="5" class="input resize-none" :placeholder="t('knowledge.laws.contentPlaceholder')" />
        </div>
        <div class="grid grid-cols-2 gap-3">
          <BaseInput v-model="form.sourceRef" :label="t('common.source')" :placeholder="t('knowledge.laws.sourcePlaceholder')" />
          <BaseInput v-model="form.effectiveDate" :label="t('knowledge.laws.colEffective')" type="date" />
        </div>
        <div class="rounded-md bg-raised border border-line p-3 text-xs text-ink-muted leading-relaxed">
          {{ t('knowledge.laws.vectorizeNote') }}
        </div>
      </div>
      <template #footer>
        <BaseButton variant="secondary" @click="editOpen = false">{{ t('common.cancel') }}</BaseButton>
        <BaseButton icon="check" :loading="saving" @click="submitSave">{{ editing ? t('common.save') : t('knowledge.laws.saveAndVectorize') }}</BaseButton>
      </template>
    </BaseModal>

    <!-- Excel batch-import modal -->
    <BaseModal v-model:open="importOpen" :title="t('knowledge.laws.importTitle')" width="max-w-lg" @close="importOpen = false; importFile = null; importResult = null">
      <div class="space-y-4">
        <div class="rounded-md bg-raised border border-line p-3.5">
          <p class="text-xs font-semibold text-ink-muted mb-2">{{ t('knowledge.laws.importTemplate') }}</p>
          <div class="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs text-ink-muted font-mono">
            <span>{{ t('knowledge.laws.colDocTypeDesc') }}</span>
            <span>{{ t('knowledge.laws.colTitleDesc') }}</span>
            <span>{{ t('knowledge.laws.colContentDesc') }}</span>
            <span>{{ t('knowledge.laws.colSourceDesc') }}</span>
            <span>{{ t('knowledge.laws.colEffectiveDesc') }}</span>
            <span>{{ t('knowledge.laws.colExpiryDesc') }}</span>
          </div>
        </div>

        <button
          class="w-full border-2 border-dashed rounded-lg p-6 text-center transition-colors cursor-pointer"
          :class="importFile ? 'border-accent bg-accent-soft/40' : 'border-line-control hover:border-accent'"
          @click="($refs.importInput as HTMLInputElement).click()"
        >
          <input ref="importInput" type="file" class="hidden" accept=".xlsx,.xls,.csv" @change="pickImportFile(($event.target as HTMLInputElement).files?.[0] ?? null)" />
          <Icon :name="importFile ? 'file-text' : 'download'" :size="24" class="mx-auto" :class="importFile ? 'text-accent' : 'text-line-control'" />
          <p class="mt-2 text-sm font-medium text-ink">{{ importFile ? importFile.name : t('knowledge.laws.pickFile') }}</p>
          <p v-if="!importFile" class="mt-1 text-xs text-ink-faint">{{ t('knowledge.laws.fileHint') }}</p>
        </button>

        <div v-if="importResult" class="rounded-md border border-success-200 bg-success-50/60 p-3 text-sm text-success-800">
          {{ t('knowledge.laws.importResult', { imported: importResult.imported, vectorized: importResult.vectorized }) }}
        </div>
        <div v-else class="rounded-md bg-raised border border-line p-3 text-xs text-ink-muted leading-relaxed">
          {{ t('knowledge.laws.importFlow') }}
        </div>
      </div>
      <template #footer>
        <BaseButton variant="secondary" @click="importOpen = false">{{ t('common.close') }}</BaseButton>
        <BaseButton icon="download" :loading="importing" :disabled="!importFile" @click="submitImport">{{ importing ? t('knowledge.laws.importing') : t('knowledge.laws.startImport') }}</BaseButton>
      </template>
    </BaseModal>
  </div>
</template>

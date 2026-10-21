<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { fetchTemplates, saveTemplate, deleteTemplate } from '@/api/knowledge'
import { qk } from '@/api/queryKeys'
import { useApiList, useApiMutation } from '@/composables/useApiQuery'
import type { ContractTemplate, ContractType } from '@/types'
import { contractTypeLabels } from '@/utils/format'
import { toastSuccess, toastError } from '@/plugins/toast'
import PageHeader from '@/components/ui/PageHeader.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseBadge from '@/components/ui/BaseBadge.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseInput from '@/components/ui/BaseInput.vue'
import BaseSelect from '@/components/ui/BaseSelect.vue'
import Icon from '@/components/ui/Icon.vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const route = useRoute()

// ===== Data layer: TanStack Query =====
const { list: templates, loading } = useApiList(qk.knowledge.templates(), () => fetchTemplates())

const activeType = ref<ContractType>('purchase')
// Initial keyword may come from the top-bar global search (?q=...)
const keyword = ref(String(route.query.q ?? '').trim())

// ===== Create/edit clause =====
const editOpen = ref(false)
const editing = ref<ContractTemplate | null>(null)
const saving = ref(false)
const form = ref<{ name: string; contractType: ContractType; clauseLevel: ContractTemplate['clauseLevel']; content: string }>({
  name: '',
  contractType: 'purchase',
  clauseLevel: 'recommended',
  content: '',
})

const typeOptions = (Object.keys(contractTypeLabels) as ContractType[]).map((v) => ({ value: v, label: contractTypeLabels[v] }))
const levelOptions = computed(() => [
  { value: 'required', label: t('knowledge.templates.levelRequired') },
  { value: 'recommended', label: t('knowledge.templates.levelRecommended') },
  { value: 'optional', label: t('knowledge.templates.levelOptional') },
])

function openCreate() {
  editing.value = null
  form.value = { name: '', contractType: activeType.value, clauseLevel: 'recommended', content: '' }
  editOpen.value = true
}

function openEdit(item: ContractTemplate) {
  editing.value = item
  form.value = { name: item.name, contractType: item.contractType, clauseLevel: item.clauseLevel, content: item.content }
  editOpen.value = true
}

// ===== Mutation: save / delete clause =====
const saveMutation = useApiMutation(
  (payload: Parameters<typeof saveTemplate>[0]) => saveTemplate(payload),
  {
    invalidate: qk.knowledge.templates(),
    onSuccess: (_data, payload) => {
      toastSuccess(
        payload.id ? t('knowledge.templates.toastUpdated') : t('knowledge.templates.toastCreated'),
      )
    },
    onError: (e) => toastError(e instanceof Error ? e.message : t('common.saveFailed')),
  },
)

const deleteMutation = useApiMutation((id: number) => deleteTemplate(id), {
  invalidate: qk.knowledge.templates(),
  onSuccess: (_data, id) => {
    const found = templates.value.find((x) => x.id === id)
    toastSuccess(t('knowledge.templates.toastDeleted', { name: found?.name ?? id }))
  },
  onError: (e) => toastError(e instanceof Error ? e.message : t('common.deleteFailed')),
})

async function submitSave() {
  if (!form.value.name.trim() || !form.value.content.trim()) {
    toastError(t('knowledge.templates.fieldsRequired'))
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      await saveMutation.mutateAsync({ id: editing.value.id, ...form.value })
    } else {
      await saveMutation.mutateAsync({ ...form.value })
    }
    editOpen.value = false
    activeType.value = form.value.contractType
  } catch (e) {
    toastError(e instanceof Error ? e.message : t('common.saveFailed'))
  } finally {
    saving.value = false
  }
}

// ===== Delete confirmation =====
const deleteTarget = ref<ContractTemplate | null>(null)
const deleting = ref(false)

async function submitDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    await deleteMutation.mutateAsync(deleteTarget.value.id)
    deleteTarget.value = null
  } catch (e) {
    toastError(e instanceof Error ? e.message : t('common.deleteFailed'))
  } finally {
    deleting.value = false
  }
}

const types = computed(() => Array.from(new Set(templates.value.map((item) => item.contractType))) as ContractType[])

const grouped = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  const list = templates.value.filter(
    (t) =>
      t.contractType === activeType.value &&
      (!kw || t.name.toLowerCase().includes(kw) || t.content.toLowerCase().includes(kw)),
  )
  return [
    { level: 'required' as const, title: t('knowledge.templates.groupRequired'), desc: t('knowledge.templates.descRequired'), tone: 'danger' as const },
    { level: 'recommended' as const, title: t('knowledge.templates.groupRecommended'), desc: t('knowledge.templates.descRecommended'), tone: 'warn' as const },
    { level: 'optional' as const, title: t('knowledge.templates.groupOptional'), desc: t('knowledge.templates.descOptional'), tone: 'info' as const },
  ].map((g) => ({ ...g, items: list.filter((item) => item.clauseLevel === g.level) }))
})

const levelBadge = computed<Record<string, { label: string; tone: 'danger' | 'warn' | 'info' }>>(() => ({
  required: { label: t('knowledge.templates.badgeRequired'), tone: 'danger' },
  recommended: { label: t('knowledge.templates.badgeRecommended'), tone: 'warn' },
  optional: { label: t('knowledge.templates.badgeOptional'), tone: 'info' },
}))
</script>

<template>
  <div>
    <PageHeader
      :title="t('knowledge.templates.title')"
      :description="t('knowledge.templates.description')"
    >
      <template #actions>
        <BaseButton icon="plus" @click="openCreate">{{ t('knowledge.templates.create') }}</BaseButton>
      </template>
    </PageHeader>

    <div v-if="loading" class="card p-20 text-center">
      <Icon name="refresh" :size="28" class="inline-block animate-spin text-ink-faint" />
    </div>

    <template v-else>
      <!-- Type switch + keyword filter -->
      <div class="card p-2 mb-4 flex flex-wrap items-center gap-1.5">
        <button
          v-for="item in types"
          :key="item"
          class="px-3.5 py-1.5 rounded-md text-sm font-medium transition-colors"
          :class="activeType === item ? 'bg-accent text-white' : 'text-ink-muted hover:bg-line-rule'"
          @click="activeType = item"
        >{{ contractTypeLabels[item] }}</button>
        <div class="relative ml-auto w-full sm:w-64">
          <Icon name="search" :size="15" class="absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" />
          <input
            v-model="keyword"
            class="input pl-9 h-8"
            :placeholder="t('knowledge.templates.searchPlaceholder')"
            :aria-label="t('knowledge.templates.searchPlaceholder')"
          />
        </div>
      </div>

      <!-- Three-tier clause grouping -->
      <div class="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div v-for="g in grouped" :key="g.level" class="space-y-3">
          <div class="flex items-center gap-2 px-1">
            <BaseBadge :tone="g.tone">{{ g.title }}</BaseBadge>
            <span class="text-xs text-ink-faint">{{ g.desc }}</span>
            <span class="ml-auto text-xs text-ink-faint font-mono">{{ t('knowledge.templates.countItems', { n: g.items.length }) }}</span>
          </div>
          <BaseCard v-for="item in g.items" :key="item.id" padding="p-4">
            <div class="flex items-center justify-between gap-2">
              <p class="text-sm font-semibold text-ink">{{ item.name }}</p>
              <div class="flex items-center gap-1">
                <span class="text-xs text-ink-faint font-mono">v{{ item.version }}</span>
                <button
                  class="p-1 rounded-md text-ink-faint hover:bg-accent-soft hover:text-accent"
                  :title="t('common.edit')"
                  @click="openEdit(item)"
                >
                  <Icon name="edit" :size="14" />
                </button>
                <button
                  class="p-1 rounded-md text-ink-faint hover:bg-danger-50 hover:text-danger-600"
                  :title="t('common.delete')"
                  @click="deleteTarget = item"
                >
                  <Icon name="trash" :size="14" />
                </button>
              </div>
            </div>
            <p class="mt-2 text-sm text-ink-muted leading-relaxed">{{ item.content }}</p>
            <div class="mt-3 pt-2.5 border-t border-line-rule flex items-center gap-2 text-xs text-ink-faint">
              <Icon name="database" :size="12" />
              {{ t('knowledge.templates.vectorizedNote') }}
            </div>
          </BaseCard>
          <p v-if="g.items.length === 0" class="py-8 text-center text-sm text-ink-faint rounded-lg border border-dashed border-line">
            {{ t('knowledge.templates.emptyGroup', { title: g.title }) }}
          </p>
        </div>
      </div>

      <p class="mt-4 text-xs text-ink-faint">
        {{ t('knowledge.templates.versionNote') }}
      </p>
    </template>

    <!-- Create/edit modal -->
    <BaseModal v-model:open="editOpen" :title="editing ? t('knowledge.templates.editTitle', { name: editing.name }) : t('knowledge.templates.createTitle')" width="max-w-xl" @close="editOpen = false">
      <div class="space-y-4">
        <BaseInput v-model="form.name" :label="t('knowledge.templates.fieldName')" :placeholder="t('knowledge.templates.namePlaceholder')" />
        <div class="grid grid-cols-2 gap-3">
          <BaseSelect v-model="form.contractType" :label="t('knowledge.templates.fieldType')" :options="typeOptions" />
          <BaseSelect v-model="form.clauseLevel" :label="t('knowledge.templates.fieldLevel')" :options="levelOptions" />
        </div>
        <div>
          <label class="label">{{ t('knowledge.templates.fieldContent') }}</label>
          <textarea v-model="form.content" rows="5" class="input resize-none" :placeholder="t('knowledge.templates.contentPlaceholder')" />
        </div>
        <div class="rounded-md bg-raised border border-line p-3 text-xs text-ink-muted leading-relaxed">
          {{ editing ? t('knowledge.templates.editNote') : t('knowledge.templates.createNote') }}
        </div>
      </div>
      <template #footer>
        <BaseButton variant="secondary" @click="editOpen = false">{{ t('common.cancel') }}</BaseButton>
        <BaseButton icon="check" :loading="saving" @click="submitSave">{{ editing ? t('knowledge.templates.saveNewVersion') : t('knowledge.templates.saveAndEmbed') }}</BaseButton>
      </template>
    </BaseModal>

    <!-- Delete confirmation -->
    <BaseModal :open="!!deleteTarget" :title="t('knowledge.templates.deleteTitle')" width="max-w-md" @close="deleteTarget = null">
      <div class="flex items-start gap-3">
        <Icon name="alert-triangle" :size="22" class="mt-0.5 text-danger-500 shrink-0" />
        <div class="text-sm text-ink-muted leading-relaxed">
          {{ t('knowledge.templates.deleteConfirm', { name: deleteTarget?.name, type: contractTypeLabels[deleteTarget?.contractType ?? 'purchase'], version: deleteTarget?.version }) }}
          <p class="mt-1.5 text-xs text-ink-faint">{{ t('knowledge.templates.deleteHint') }}</p>
        </div>
      </div>
      <template #footer>
        <BaseButton variant="secondary" @click="deleteTarget = null">{{ t('common.cancel') }}</BaseButton>
        <BaseButton variant="danger" icon="trash" :loading="deleting" @click="submitDelete">{{ t('knowledge.templates.confirmDelete') }}</BaseButton>
      </template>
    </BaseModal>
  </div>
</template>

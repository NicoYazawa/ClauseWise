<script setup lang="ts">
import { ref } from 'vue'
import { fetchModelVersions, setDefaultModel, fetchPrompts, savePromptContent, activatePrompt } from '@/api/system'
import { qk } from '@/api/queryKeys'
import { useApiList, useApiMutation } from '@/composables/useApiQuery'
import type { ModelVersion, PromptTemplate } from '@/types'
import { formatDateTime } from '@/utils/format'
import { toastSuccess, toastError } from '@/plugins/toast'
import PageHeader from '@/components/ui/PageHeader.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseBadge from '@/components/ui/BaseBadge.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseDrawer from '@/components/ui/BaseDrawer.vue'
import Icon from '@/components/ui/Icon.vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

// ===== Data layer: TanStack Query =====
const { list: models, loading } = useApiList(qk.system.models(), () => fetchModelVersions())
const { list: prompts } = useApiList(qk.system.prompts(), () => fetchPrompts())

const switching = ref(false)

const switchMutation = useApiMutation((id: number) => setDefaultModel(id), {
  invalidate: qk.system.models(),
  onSuccess: (_data, id) => {
    const m = models.value.find((x) => x.id === id)
    toastSuccess(t('system.models.toastSwitched', { name: m?.modelName ?? id }))
  },
  onError: (e) => toastError(e instanceof Error ? e.message : t('system.models.switchFailed')),
})

async function onSetDefault(m: ModelVersion) {
  switching.value = true
  try {
    await switchMutation.mutateAsync(m.id)
  } catch (e) {
    toastError(e instanceof Error ? e.message : t('system.models.switchFailed'))
  } finally {
    switching.value = false
  }
}

// ===== Prompt editing =====
const editing = ref<PromptTemplate | null>(null)
const draft = ref('')
const saving = ref(false)

function openEdit(p: PromptTemplate) {
  editing.value = p
  draft.value = p.content
}

const savePromptMutation = useApiMutation(
  (payload: { id: number; content: string }) => savePromptContent(payload.id, payload.content),
  {
    invalidate: qk.system.prompts(),
    onSuccess: (p) => {
      toastSuccess(t('system.models.toastPublishedPrompt', { version: p.version }))
      editing.value = null
    },
    onError: (e) => toastError(e instanceof Error ? e.message : t('common.saveFailed')),
  },
)

async function submitPrompt() {
  if (!editing.value) return
  saving.value = true
  try {
    await savePromptMutation.mutateAsync({ id: editing.value.id, content: draft.value })
  } catch (e) {
    toastError(e instanceof Error ? e.message : t('common.saveFailed'))
  } finally {
    saving.value = false
  }
}

const activateMutation = useApiMutation((id: number) => activatePrompt(id), {
  invalidate: qk.system.prompts(),
  onSuccess: (_data, id) => {
    const p = prompts.value.find((x) => x.id === id)
    toastSuccess(t('system.models.toastActivatedPrompt', { scene: p?.scene ?? '', version: p?.version ?? '' }))
  },
  onError: (e) => toastError(e instanceof Error ? e.message : t('system.models.activateFailed')),
})

async function onActivate(p: PromptTemplate) {
  try {
    await activateMutation.mutateAsync(p.id)
  } catch (e) {
    toastError(e instanceof Error ? e.message : t('system.models.activateFailed'))
  }
}
</script>

<template>
  <div>
    <PageHeader
      :title="t('system.models.title')"
      :description="t('system.models.description')"
    >
      <template #breadcrumb>
        <span>{{ t('menu.system') }}</span>
        <Icon name="chevron-right" :size="12" />
        <span class="text-ink-muted">{{ t('system.models.title') }}</span>
      </template>
    </PageHeader>

    <div v-if="loading" class="card p-20 text-center">
      <Icon name="refresh" :size="28" class="inline-block animate-spin text-ink-faint" />
    </div>

    <template v-else>
      <!-- Model versions -->
      <BaseCard
        :title="t('system.models.modelsTitle')"
        :subtitle="t('system.models.modelsSubtitle')"
        class="mb-4"
      >
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b border-line text-xs text-ink-faint text-left">
                <th class="py-2.5 pr-4 font-medium">{{ t('system.models.colModelId') }}</th>
                <th class="py-2.5 pr-4 font-medium">{{ t('common.type') }}</th>
                <th class="py-2.5 pr-4 font-medium">{{ t('system.models.colAccuracy') }}</th>
                <th class="py-2.5 pr-4 font-medium">{{ t('system.models.colFalsePositive') }}</th>
                <th class="py-2.5 pr-4 font-medium">{{ t('system.models.colAdoption') }}</th>
                <th class="py-2.5 pr-4 font-medium">{{ t('system.models.colOnlineAt') }}</th>
                <th class="py-2.5 font-medium">{{ t('system.models.colStatusAction') }}</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-raised">
              <tr v-for="m in models" :key="m.id" class="text-ink-muted">
                <td class="py-3 pr-4 font-mono text-xs">{{ m.modelName }}</td>
                <td class="py-3 pr-4">
                  <BaseBadge :tone="m.modelType === 'llm' ? 'primary' : 'info'">{{ m.modelType === 'llm' ? t('system.models.typeLlm') : t('system.models.typeEmbedding') }}</BaseBadge>
                </td>
                <td class="py-3 pr-4 tabular-nums">{{ (m.evalMetrics.accuracy * 100).toFixed(0) }}%</td>
                <td class="py-3 pr-4 tabular-nums">{{ (m.evalMetrics.falsePositive * 100).toFixed(0) }}%</td>
                <td class="py-3 pr-4 tabular-nums">{{ m.evalMetrics.adoptionRate != null ? `${(m.evalMetrics.adoptionRate * 100).toFixed(0)}%` : '—' }}</td>
                <td class="py-3 pr-4 text-xs text-ink-faint">{{ formatDateTime(m.activatedAt) }}</td>
                <td class="py-3">
                  <div class="flex items-center gap-2">
                    <BaseBadge v-if="m.isDefault" tone="success">{{ t('system.models.currentEffective') }}</BaseBadge>
                    <button v-else class="text-xs text-accent hover:underline" :disabled="switching" @click="onSetDefault(m)">{{ t('system.models.setDefault') }}</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="mt-3 text-xs text-ink-faint">
          {{ t('system.models.modelNote') }}
        </p>
      </BaseCard>

      <!-- Prompt templates -->
      <BaseCard :title="t('system.models.promptsTitle')" :subtitle="t('system.models.promptsSubtitle')">
        <div class="space-y-3">
          <div
            v-for="p in prompts"
            :key="p.id"
            class="rounded-lg border p-4 transition-colors"
            :class="p.isActive ? 'border-accent-track bg-accent-soft/30' : 'border-line'"
          >
            <div class="flex flex-wrap items-center gap-2.5">
              <BaseBadge tone="slate">{{ p.scene }}</BaseBadge>
              <span class="font-mono text-sm font-semibold text-ink">{{ p.version }}</span>
              <BaseBadge v-if="p.isActive" tone="success">{{ t('system.models.activeTag') }}</BaseBadge>
              <span class="ml-auto flex items-center gap-3">
                <span class="text-xs text-ink-faint">{{ formatDateTime(p.updatedAt) }}</span>
                <button class="text-xs text-accent hover:underline" @click="openEdit(p)">{{ t('common.edit') }}</button>
                <button v-if="!p.isActive" class="text-xs text-ink-muted hover:text-accent hover:underline" @click="onActivate(p)">{{ t('system.models.activateVersion') }}</button>
              </span>
            </div>
            <pre class="mt-3 rounded-md bg-raised border border-line-rule p-3 text-xs text-ink-muted leading-relaxed whitespace-pre-wrap max-h-28 overflow-y-auto">{{ p.content }}</pre>
          </div>
        </div>
      </BaseCard>
    </template>

    <!-- Prompt edit drawer -->
    <BaseDrawer
      :open="!!editing"
      :title="t('system.models.drawerTitle', { scene: editing?.scene ?? '', version: editing?.version ?? '' })"
      @close="editing = null"
    >
      <div v-if="editing" class="space-y-4">
        <div class="rounded-md bg-raised border border-line p-3 text-xs text-ink-muted leading-relaxed">
          {{ t('system.models.varIntro') }}
          <span class="font-mono">{contract_type}</span> {{ t('system.models.varContractType') }}
          <span class="font-mono">{clause_text}</span> {{ t('system.models.varClauseText') }}
          <span class="font-mono">{rag_context}</span> {{ t('system.models.varRagContext') }}
          <span class="font-mono">{old_clause}</span> / <span class="font-mono">{new_clause}</span> {{ t('system.models.varDiff') }}
          {{ t('system.models.publishNote') }}
        </div>
        <textarea v-model="draft" rows="18" class="input font-mono text-xs leading-relaxed" :placeholder="t('system.models.promptPlaceholder')" />
        <div class="rounded-md bg-warn-50/60 border border-warn-200 p-3 text-xs text-warn-700 leading-relaxed">
          {{ t('system.models.warnNote') }}
        </div>
        <div class="flex justify-end gap-2 pt-1">
          <BaseButton variant="secondary" @click="editing = null">{{ t('common.cancel') }}</BaseButton>
          <BaseButton icon="check" :loading="saving" @click="submitPrompt">{{ t('system.models.publishBtn') }}</BaseButton>
        </div>
      </div>
    </BaseDrawer>
  </div>
</template>

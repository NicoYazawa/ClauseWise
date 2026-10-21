<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { fetchRoles, updateRolePermissions } from '@/api/system'
import { qk } from '@/api/queryKeys'
import { useApiList, useApiMutation } from '@/composables/useApiQuery'
import type { RoleInfo } from '@/types'
import { toastError, toastSuccess } from '@/plugins/toast'
import PageHeader from '@/components/ui/PageHeader.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseBadge from '@/components/ui/BaseBadge.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import Icon from '@/components/ui/Icon.vue'
import { translateData } from '@/utils/i18nData'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

// ===== Data layer: TanStack Query =====
const { list: roles, loading } = useApiList(qk.system.roles(), () => fetchRoles())

const activeCode = ref('')
const saving = ref(false)
const draft = ref<string[]>([])

// Auto-select the first role once the role list arrives
watch(
  roles,
  (list) => {
    if (!activeCode.value && list.length > 0) selectRole(list[0].code)
  },
  { immediate: true },
)

const activeRole = computed(() => roles.value.find((r) => r.code === activeCode.value) ?? null)

function selectRole(code: string) {
  activeCode.value = code
  const role = roles.value.find((r) => r.code === code)
  draft.value = [...(role?.permissions ?? [])]
}

/** Permission-point matrix: module x permission point (codes stay in sync with the backend) */
const permissionMatrix = computed(() => [
  { module: t('data.perm.moduleContract'), perms: [
    { code: 'contract:upload', label: t('data.perm.contractUpload') },
    { code: 'contract:download', label: t('data.perm.contractDownload') },
    { code: 'contract:delete', label: t('data.perm.contractDelete') },
  ] },
  { module: t('data.perm.moduleReview'), perms: [
    { code: 'review:rerun', label: t('data.perm.reviewRerun') },
    { code: 'review:export', label: t('data.perm.reviewExport') },
  ] },
  { module: t('data.perm.moduleWorkflow'), perms: [
    { code: 'workflow:approve', label: t('data.perm.workflowApprove') },
    { code: 'workflow:define', label: t('data.perm.workflowDefine') },
  ] },
  { module: t('data.perm.moduleKnowledge'), perms: [
    { code: 'knowledge:manage', label: t('data.perm.knowledgeManage') },
  ] },
  { module: t('data.perm.moduleSystem'), perms: [
    { code: 'system:user', label: t('data.perm.systemUser') },
    { code: 'system:role', label: t('data.perm.systemRole') },
    { code: 'system:audit', label: t('data.perm.systemAudit') },
  ] },
])

const scopeLabels = computed<Record<string, string>>(() => ({
  self: t('data.scope.self'),
  dept: t('data.scope.dept'),
  all: t('data.scope.all'),
}))

function togglePerm(code: string) {
  draft.value = draft.value.includes(code) ? draft.value.filter((c) => c !== code) : [...draft.value, code]
}

const saveMutation = useApiMutation(
  (payload: { code: string; permissions: string[] }) => updateRolePermissions(payload.code, payload.permissions),
  {
    invalidate: qk.system.roles(),
    onSuccess: (_data, payload) => {
      const r = roles.value.find((x) => x.code === payload.code)
      if (r) r.permissions = [...payload.permissions]
      toastSuccess(t('system.roles.toastSaved', { name: r?.name ?? payload.code }))
    },
    onError: (e) => toastError(e instanceof Error ? e.message : t('common.saveFailed')),
  },
)

async function save() {
  if (!activeRole.value) return
  saving.value = true
  try {
    await saveMutation.mutateAsync({ code: activeRole.value.code, permissions: draft.value })
  } catch {
    /* 错误已由 mutation 的 onError 统一提示，这里仅避免未处理的 Promise 拒绝 */
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div>
    <PageHeader
      :title="t('system.roles.title')"
      :description="t('system.roles.description')"
    >
      <template #breadcrumb>
        <span>{{ t('menu.system') }}</span>
        <Icon name="chevron-right" :size="12" />
        <span class="text-ink-muted">{{ t('system.roles.title') }}</span>
      </template>
    </PageHeader>

    <div v-if="loading" class="card p-20 text-center">
      <Icon name="refresh" :size="28" class="inline-block animate-spin text-ink-faint" />
    </div>

    <div v-else class="grid grid-cols-1 xl:grid-cols-4 gap-4">
      <!-- Role list -->
      <div class="xl:col-span-1 space-y-2.5">
        <button
          v-for="r in roles"
          :key="r.code"
          class="w-full text-left rounded-lg border p-4 transition-colors"
          :class="activeCode === r.code ? 'border-accent bg-accent-soft/60' : 'border-line bg-white hover:border-accent-track'"
          @click="selectRole(r.code)"
        >
          <div class="flex items-center justify-between">
            <span class="text-sm font-semibold text-ink">{{ translateData(r.name) }}</span>
            <BaseBadge tone="slate">{{ t('system.roles.permCount', { n: r.permissions.length }) }}</BaseBadge>
          </div>
          <p class="mt-1 text-xs text-ink-faint font-mono">{{ r.code }}</p>
          <p class="mt-1.5 text-xs text-ink-muted line-clamp-2">{{ r.description }}</p>
          <p class="mt-2 text-xs text-ink-faint">{{ t('system.roles.dataScopeLabel', { scope: scopeLabels[r.dataScope] }) }}</p>
        </button>
      </div>

      <!-- Permission matrix -->
      <BaseCard
        v-if="activeRole"
        :title="t('system.roles.matrixTitle', { name: activeRole.name })"
        :subtitle="t('system.roles.matrixSubtitle', { n: draft.length })"
        class="xl:col-span-3"
      >
        <template #actions>
          <BaseButton size="sm" icon="check" :loading="saving" :disabled="draft.length === activeRole.permissions.length" @click="save">{{ t('system.roles.saveChange') }}</BaseButton>
        </template>

        <div class="overflow-x-auto">
          <table class="w-full">
            <thead>
              <tr class="border-b border-line">
                <th class="table-th w-32">{{ t('system.roles.colModule') }}</th>
                <th class="table-th">{{ t('system.roles.colPerms') }}</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-line-rule">
              <tr v-for="row in permissionMatrix" :key="row.module">
                <td class="table-td font-medium text-ink">{{ row.module }}</td>
                <td class="table-td">
                  <div class="flex flex-wrap gap-2">
                    <label
                      v-for="p in row.perms"
                      :key="p.code"
                      class="inline-flex items-center gap-2 rounded-md border px-3 py-1.5 cursor-pointer transition-colors"
                      :class="draft.includes(p.code) ? 'border-accent bg-accent-soft' : 'border-line hover:border-accent-track'"
                    >
                      <input
                        type="checkbox"
                        class="h-3.5 w-3.5 accent-accent"
                        :checked="draft.includes(p.code)"
                        @change="togglePerm(p.code)"
                      />
                      <span class="text-xs font-medium" :class="draft.includes(p.code) ? 'text-accent-ink' : 'text-ink-muted'">{{ p.label }}</span>
                      <span class="text-[10px] font-mono text-ink-faint">{{ p.code }}</span>
                    </label>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="mt-4 rounded-md bg-raised border border-line p-3.5 text-xs text-ink-muted leading-relaxed">
          <p class="flex items-center gap-1.5 font-medium text-ink-muted"><Icon name="lock" :size="13" /> {{ t('system.roles.noteTitle') }}</p>
          <p class="mt-1.5">
            {{ t('system.roles.noteBody') }}
          </p>
        </div>
      </BaseCard>
    </div>
  </div>
</template>

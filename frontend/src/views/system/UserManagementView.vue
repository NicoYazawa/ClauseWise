<script setup lang="ts">
import { computed, ref } from 'vue'
import { fetchUsers, fetchRoles, toggleUser, updateUserRoles, createUser, resetPassword } from '@/api/system'
import { qk } from '@/api/queryKeys'
import { useApiList, useApiMutation } from '@/composables/useApiQuery'
import type { User, RoleInfo } from '@/types'
import { formatDateTime, maskPhone } from '@/utils/format'
import { translateData } from '@/utils/i18nData'
import { toastSuccess, toastError } from '@/plugins/toast'
import PageHeader from '@/components/ui/PageHeader.vue'
import BaseTable from '@/components/ui/BaseTable.vue'
import BaseBadge from '@/components/ui/BaseBadge.vue'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/ui/BaseInput.vue'
import Icon from '@/components/ui/Icon.vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

// ===== Data layer: TanStack Query =====
const { list: users, loading } = useApiList(qk.system.users(), () => fetchUsers())
const { list: roles } = useApiList(qk.system.roles(), () => fetchRoles())

const keyword = ref('')

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return kw
    ? users.value.filter((u) => u.realName.toLowerCase().includes(kw) || u.username.includes(kw) || u.deptName.includes(kw))
    : users.value
})

// ===== Mutation: enable/disable =====
const toggleMutation = useApiMutation((id: number) => toggleUser(id), {
  invalidate: qk.system.users(),
  onSuccess: (_data, id) => {
    const u = users.value.find((x) => x.id === id)
    toastSuccess(
      u?.isActive
        ? t('system.users.toastDisabledAccount', { username: u.username })
        : t('system.users.toastEnabledAccount', { username: u?.username ?? id }),
    )
  },
  onError: (e) => toastError(e instanceof Error ? e.message : t('common.operateFailed')),
})

async function onToggle(u: User) {
  try {
    await toggleMutation.mutateAsync(u.id)
  } catch {
    /* 错误已由 mutation 的 onError 统一提示，这里仅避免未处理的 Promise 拒绝 */
  }
}

// ===== Role assignment =====
const roleTarget = ref<User | null>(null)
const selectedRoles = ref<string[]>([])
const saving = ref(false)

const rolesMutation = useApiMutation(
  (payload: { id: number; roles: string[] }) => updateUserRoles(payload.id, payload.roles),
  {
    invalidate: qk.system.users(),
    onSuccess: (_data, payload) => {
      const u = users.value.find((x) => x.id === payload.id)
      toastSuccess(t('system.users.toastRolesUpdated', { name: u?.realName ?? payload.id }))
    },
    onError: (e) => toastError(e instanceof Error ? e.message : t('common.saveFailed')),
  },
)

function openRoles(u: User) {
  roleTarget.value = u
  selectedRoles.value = [...u.roles]
}

async function submitRoles() {
  if (!roleTarget.value) return
  saving.value = true
  try {
    await rolesMutation.mutateAsync({ id: roleTarget.value.id, roles: selectedRoles.value })
    roleTarget.value = null
  } catch (e) {
    toastError(e instanceof Error ? e.message : t('common.saveFailed'))
  } finally {
    saving.value = false
  }
}

function roleName(code: string): string {
  return translateData(roles.value.find((r) => r.code === code)?.name) || code
}

// ===== Create user =====
const createOpen = ref(false)
const creating = ref(false)
const createForm = ref({ username: '', realName: '', deptName: '法务部', title: '', phone: '', roles: [] as string[] })
/** Department options: value carries the backend's Chinese dept name, label is rendered in the active language */
const deptOptions = computed(() => [
  { value: '法务部', label: t('data.dept.legal') },
  { value: '采购部', label: t('data.dept.procurement') },
  { value: '销售部', label: t('data.dept.sales') },
  { value: '审计部', label: t('data.dept.audit') },
  { value: '信息管理部', label: t('data.dept.it') },
  { value: '财务部', label: t('data.dept.finance') },
])

function openCreate() {
  createForm.value = { username: '', realName: '', deptName: '法务部', title: '', phone: '', roles: [] }
  createOpen.value = true
}

function toggleCreateRole(code: string) {
  const i = createForm.value.roles.indexOf(code)
  if (i >= 0) createForm.value.roles.splice(i, 1)
  else createForm.value.roles.push(code)
}

const createMutation = useApiMutation(
  (payload: Parameters<typeof createUser>[0]) => createUser(payload),
  {
    invalidate: qk.system.users(),
    onSuccess: (u) => {
      toastSuccess(t('system.users.toastCreatedAccount', { username: u.username }))
      createOpen.value = false
    },
    onError: (e) => toastError(e instanceof Error ? e.message : t('system.users.createFailed')),
  },
)

async function submitCreate() {
  creating.value = true
  try {
    await createMutation.mutateAsync({ ...createForm.value })
  } catch (e) {
    toastError(e instanceof Error ? e.message : t('system.users.createFailed'))
  } finally {
    creating.value = false
  }
}

// ===== Reset password =====
const resetTarget = ref<User | null>(null)
const resetting = ref(false)

const resetMutation = useApiMutation((id: number) => resetPassword(id), {
  onSuccess: (_data, id) => {
    const u = users.value.find((x) => x.id === id)
    toastSuccess(t('system.users.toastResetDone', { name: u?.realName ?? id }))
    resetTarget.value = null
  },
  onError: (e) => toastError(e instanceof Error ? e.message : t('system.users.resetFailed')),
})

async function submitReset() {
  if (!resetTarget.value) return
  resetting.value = true
  try {
    await resetMutation.mutateAsync(resetTarget.value.id)
  } catch (e) {
    toastError(e instanceof Error ? e.message : t('system.users.resetFailed'))
  } finally {
    resetting.value = false
  }
}
</script>

<template>
  <div>
    <PageHeader
      :title="t('system.users.title')"
      :description="t('system.users.description')"
    >
      <template #breadcrumb>
        <span>{{ t('menu.system') }}</span>
        <Icon name="chevron-right" :size="12" />
        <span class="text-ink-muted">{{ t('system.users.title') }}</span>
      </template>
      <template #actions>
        <BaseButton icon="plus" @click="openCreate">{{ t('system.users.create') }}</BaseButton>
      </template>
    </PageHeader>

    <div class="card p-4 mb-4">
      <div class="relative max-w-md">
        <Icon name="search" :size="15" class="absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" />
        <input v-model="keyword" class="input pl-9" :placeholder="t('system.users.searchPlaceholder')" />
      </div>
    </div>

    <div class="card">
      <BaseTable
        :columns="[
          { key: 'name', label: t('system.users.colUser') },
          { key: 'dept', label: t('system.users.colDept'), width: '180px' },
          { key: 'phone', label: t('system.users.colPhone'), width: '140px' },
          { key: 'roles', label: t('system.users.colRoles'), width: '220px' },
          { key: 'status', label: t('common.status'), width: '90px' },
          { key: 'lastLogin', label: t('system.users.colLastLogin'), width: '150px' },
          { key: 'actions', label: t('common.actions'), width: '150px' },
        ]"
        :loading="loading"
        :empty="filtered.length === 0"
      >
        <tr v-for="u in filtered" :key="u.id" class="hover:bg-raised">
          <td class="table-td">
            <div class="flex items-center gap-2.5">
              <span class="flex h-8 w-8 items-center justify-center rounded-full bg-accent-track text-xs font-semibold text-accent">{{ u.realName.slice(0, 1) }}</span>
              <div>
                <p class="font-medium text-ink">{{ u.realName }}</p>
                <p class="mt-0.5 text-xs text-ink-faint font-mono">{{ u.username }}</p>
              </div>
            </div>
          </td>
          <td class="table-td">
            <p class="text-sm text-ink">{{ translateData(u.deptName) }}</p>
            <p class="mt-0.5 text-xs text-ink-faint">{{ translateData(u.title) }}</p>
          </td>
          <td class="table-td font-mono text-xs text-ink-muted">{{ maskPhone(u.phone) }}</td>
          <td class="table-td">
            <div class="flex flex-wrap gap-1">
              <BaseBadge v-for="r in u.roles" :key="r" tone="primary">{{ roleName(r) }}</BaseBadge>
            </div>
          </td>
          <td class="table-td">
            <BaseBadge :tone="u.isActive ? 'success' : 'slate'">{{ u.isActive ? t('common.enable') : t('common.disable') }}</BaseBadge>
          </td>
          <td class="table-td text-xs text-ink-muted">{{ formatDateTime(u.lastLoginAt) }}</td>
          <td class="table-td">
            <div class="flex items-center gap-2">
              <button class="text-xs text-accent hover:underline" @click="openRoles(u)">{{ t('system.users.assignRoles') }}</button>
              <button class="text-xs text-ink-muted hover:text-accent hover:underline" @click="resetTarget = u">{{ t('system.users.resetPassword') }}</button>
              <button
                class="text-xs hover:underline"
                :class="u.isActive ? 'text-danger-600' : 'text-success-600'"
                @click="onToggle(u)"
              >{{ u.isActive ? t('common.disable') : t('common.enable') }}</button>
            </div>
          </td>
        </tr>
      </BaseTable>
    </div>

    <!-- Role assignment modal -->
    <BaseModal :open="!!roleTarget" :title="t('system.users.roleModalTitle', { name: roleTarget?.realName ?? '' })" @close="roleTarget = null">
      <div class="space-y-2">
        <label
          v-for="r in roles"
          :key="r.code"
          class="flex items-start gap-3 rounded-lg border p-3.5 cursor-pointer transition-colors"
          :class="selectedRoles.includes(r.code) ? 'border-accent bg-accent-soft/60' : 'border-line hover:border-accent-track'"
        >
          <input
            type="checkbox"
            class="mt-0.5 h-4 w-4 accent-accent"
            :checked="selectedRoles.includes(r.code)"
            @change="selectedRoles.includes(r.code) ? selectedRoles = selectedRoles.filter(x => x !== r.code) : selectedRoles.push(r.code)"
          />
          <span>
            <span class="block text-sm font-medium text-ink">{{ r.name }} <span class="ml-1 font-mono text-xs text-ink-faint">{{ r.code }}</span></span>
            <span class="block mt-0.5 text-xs text-ink-muted">{{ r.description }}</span>
          </span>
        </label>
      </div>
      <template #footer>
        <BaseButton variant="secondary" @click="roleTarget = null">{{ t('common.cancel') }}</BaseButton>
        <BaseButton icon="check" :loading="saving" @click="submitRoles">{{ t('system.users.saveAssign') }}</BaseButton>
      </template>
    </BaseModal>

    <!-- Create user modal -->
    <BaseModal v-model:open="createOpen" :title="t('system.users.createModalTitle')" width="max-w-xl" @close="createOpen = false">
      <div class="space-y-4">
        <div class="grid grid-cols-2 gap-3">
          <BaseInput v-model="createForm.username" :label="t('system.users.fieldUsername')" :placeholder="t('system.users.usernamePlaceholder')" />
          <BaseInput v-model="createForm.realName" :label="t('system.users.fieldRealName')" :placeholder="t('system.users.realNamePlaceholder')" />
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="label">{{ t('system.users.fieldDept') }}</label>
            <select v-model="createForm.deptName" class="input cursor-pointer">
              <option v-for="d in deptOptions" :key="d.value" :value="d.value">{{ d.label }}</option>
            </select>
          </div>
          <BaseInput v-model="createForm.title" :label="t('system.users.fieldTitle')" :placeholder="t('system.users.titlePlaceholder')" />
        </div>
        <BaseInput v-model="createForm.phone" :label="t('system.users.fieldPhone')" :placeholder="t('system.users.phonePlaceholder')" />
        <div>
          <label class="label">{{ t('system.users.fieldRolesCreate') }}</label>
          <div class="flex flex-wrap gap-1.5">
            <button
              v-for="r in roles"
              :key="r.code"
              type="button"
              class="px-2.5 py-1 rounded-md text-xs font-medium border transition-colors"
              :class="createForm.roles.includes(r.code) ? 'border-accent bg-accent-soft text-accent-ink' : 'border-line text-ink-muted hover:border-accent-track'"
              @click="toggleCreateRole(r.code)"
            >{{ r.name }}</button>
          </div>
        </div>
        <div class="rounded-md bg-raised border border-line p-3 text-xs text-ink-muted leading-relaxed">
          {{ t('system.users.createNote') }}
        </div>
      </div>
      <template #footer>
        <BaseButton variant="secondary" @click="createOpen = false">{{ t('common.cancel') }}</BaseButton>
        <BaseButton icon="plus" :loading="creating" @click="submitCreate">{{ t('system.users.createSubmit') }}</BaseButton>
      </template>
    </BaseModal>

    <!-- Reset password confirmation -->
    <BaseModal :open="!!resetTarget" :title="t('system.users.resetModalTitle')" width="max-w-md" @close="resetTarget = null">
      <div class="flex items-start gap-3">
        <Icon name="lock" :size="22" class="mt-0.5 text-accent shrink-0" />
        <div class="text-sm text-ink-muted leading-relaxed">
          {{ t('system.users.resetConfirm', { name: resetTarget?.realName, username: resetTarget?.username }) }}
          <p class="mt-1.5 text-xs text-ink-faint">{{ t('system.users.resetHint') }}</p>
        </div>
      </div>
      <template #footer>
        <BaseButton variant="secondary" @click="resetTarget = null">{{ t('common.cancel') }}</BaseButton>
        <BaseButton icon="lock" :loading="resetting" @click="submitReset">{{ t('system.users.confirmReset') }}</BaseButton>
      </template>
    </BaseModal>
  </div>
</template>

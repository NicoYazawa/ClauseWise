<script setup lang="ts">
import { computed, ref } from 'vue'
import { fetchAuditLogs } from '@/api/system'
import { qk } from '@/api/queryKeys'
import { useApiList } from '@/composables/useApiQuery'
import type { AuditLog } from '@/types'
import { formatDateTime } from '@/utils/format'
import { translateData } from '@/utils/i18nData'
import PageHeader from '@/components/ui/PageHeader.vue'
import BaseTable from '@/components/ui/BaseTable.vue'
import BaseBadge from '@/components/ui/BaseBadge.vue'
import BaseDrawer from '@/components/ui/BaseDrawer.vue'
import Pagination from '@/components/ui/Pagination.vue'
import Icon from '@/components/ui/Icon.vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

// ===== Data layer: TanStack Query =====
const username = ref('')
const action = ref('')
const applied = ref({ username: '', action: '' })

const { list: logs, loading } = useApiList(
  computed(() => qk.system.auditLogsFiltered(applied.value)),
  () => fetchAuditLogs({ username: applied.value.username, action: applied.value.action }),
)

function onSearch() {
  applied.value = { username: username.value, action: action.value }
  page.value = 1
}

const page = ref(1)
const pageSize = 12
const detail = ref<AuditLog | null>(null)

const filtered = computed(() => logs.value)
const paged = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))

/** Result fields are returned in Chinese by the backend; rendered in the active language here */
function resultText(raw: string): string {
  return translateData(raw)
}

/** Action classification label */
function actionTone(a: string): 'success' | 'danger' | 'info' | 'warn' | 'slate' {
  if (a === 'login') return 'info'
  if (a.includes('reject') || a.includes('disable') || a.includes('delete')) return 'danger'
  if (a.includes('approve') || a.includes('accept')) return 'success'
  if (a.includes('withdraw') || a.includes('upload')) return 'warn'
  return 'slate'
}
</script>

<template>
  <div>
    <PageHeader
      :title="t('system.audit.title')"
      :description="t('system.audit.description')"
    >
      <template #breadcrumb>
        <span>{{ t('menu.system') }}</span>
        <Icon name="chevron-right" :size="12" />
        <span class="text-ink-muted">{{ t('system.audit.title') }}</span>
      </template>
    </PageHeader>

    <div class="card p-4 mb-4 grid grid-cols-1 md:grid-cols-3 gap-3">
      <div class="relative">
        <Icon name="search" :size="15" class="absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" />
        <input v-model="username" class="input pl-9" :placeholder="t('system.audit.usernamePlaceholder')" @keyup.enter="onSearch" />
      </div>
      <input v-model="action" class="input" :placeholder="t('system.audit.actionPlaceholder')" @keyup.enter="onSearch" />
      <button class="inline-flex items-center justify-center gap-1.5 rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-ink transition-colors" @click="onSearch">
        <Icon name="search" :size="14" /> {{ t('common.search') }}
      </button>
    </div>

    <div class="card">
      <BaseTable
        :columns="[
          { key: 'time', label: t('system.audit.colTime'), width: '150px' },
          { key: 'user', label: t('common.operator'), width: '130px' },
          { key: 'action', label: t('system.audit.colAction'), width: '170px' },
          { key: 'resource', label: t('system.audit.colResource'), width: '150px' },
          { key: 'result', label: t('system.audit.colResult'), width: '80px' },
          { key: 'detail', label: t('system.audit.colDetail') },
        ]"
        :loading="loading"
        :empty="paged.length === 0"
        :empty-text="t('system.audit.empty')"
      >
        <tr v-for="l in paged" :key="l.id" class="hover:bg-raised cursor-pointer" @click="detail = l">
          <td class="table-td text-xs text-ink-muted tabular-nums">{{ formatDateTime(l.createdAt) }}</td>
          <td class="table-td">
            <p class="font-medium text-ink font-mono text-xs">{{ l.username }}</p>
          </td>
          <td class="table-td"><BaseBadge :tone="actionTone(l.action)">{{ l.action }}</BaseBadge></td>
          <td class="table-td text-xs text-ink-muted">{{ l.resourceType }} <span class="font-mono text-ink-faint">{{ l.resourceId }}</span></td>
          <td class="table-td">
            <BaseBadge :tone="l.detail.result === '成功' ? 'success' : 'danger'">{{ resultText(l.detail.result) }}</BaseBadge>
          </td>
          <td class="table-td">
            <p class="text-xs text-ink-muted truncate max-w-[320px]">{{ l.detail.extra ?? `${l.detail.ip} · ${l.detail.ua}` }}</p>
          </td>
        </tr>
      </BaseTable>
      <div class="px-4 pb-3">
        <Pagination :page="page" :page-size="pageSize" :total="filtered.length" @change="page = $event" />
      </div>
    </div>

    <!-- Detail drawer -->
    <BaseDrawer :open="!!detail" :title="t('system.audit.drawerTitle')" @close="detail = null">
      <div v-if="detail" class="space-y-4">
        <div class="flex flex-wrap gap-2">
          <BaseBadge :tone="actionTone(detail.action)">{{ detail.action }}</BaseBadge>
          <BaseBadge :tone="detail.detail.result === '成功' ? 'success' : 'danger'">{{ resultText(detail.detail.result) }}</BaseBadge>
        </div>
        <div class="divide-y divide-line-rule text-sm">
          <div class="flex justify-between py-2.5"><span class="text-ink-faint">{{ t('system.audit.recordId') }}</span><span class="font-mono text-ink">#{{ detail.id }}</span></div>
          <div class="flex justify-between py-2.5"><span class="text-ink-faint">{{ t('system.audit.operateTime') }}</span><span class="text-ink">{{ formatDateTime(detail.createdAt) }}</span></div>
          <div class="flex justify-between py-2.5"><span class="text-ink-faint">{{ t('common.operator') }}</span><span class="font-mono text-ink">{{ detail.username }}</span></div>
          <div class="flex justify-between py-2.5"><span class="text-ink-faint">{{ t('system.audit.resourceLocate') }}</span><span class="text-ink">{{ detail.resourceType }} · {{ detail.resourceId }}</span></div>
          <div class="flex justify-between py-2.5"><span class="text-ink-faint">{{ t('system.audit.sourceIp') }}</span><span class="font-mono text-ink">{{ detail.detail.ip }}</span></div>
          <div class="py-2.5"><span class="text-ink-faint">User-Agent</span><p class="mt-1 font-mono text-xs text-ink-muted bg-raised rounded px-2.5 py-1.5">{{ detail.detail.ua }}</p></div>
          <div v-if="detail.detail.extra" class="py-2.5">
            <span class="text-ink-faint">{{ t('system.audit.changeDetail') }}</span>
            <p class="mt-1 text-ink leading-relaxed">{{ detail.detail.extra }}</p>
          </div>
        </div>
        <p class="text-xs text-ink-faint leading-relaxed">
          {{ t('system.audit.note') }}
        </p>
      </div>
    </BaseDrawer>
  </div>
</template>

<script setup lang="ts">
/**
 * Global search panel: searches across contracts / the law library / the enterprise template library.
 * - Contracts use the backend keyword query (title / number / counterparty)
 * - Laws and templates are small knowledge sets, fetched once in full and filtered on the client
 * Shared by the top bar (desktop) and the top-bar search popover (mobile).
 */
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useApiList } from '@/composables/useApiQuery'
import { onClickOutside, useDebounceFn } from '@vueuse/core'
import { fetchContracts } from '@/api/contracts'
import { fetchLaws, fetchTemplates } from '@/api/knowledge'
import { qk } from '@/api/queryKeys'
import type { Contract, ContractTemplate, LawRegulation } from '@/types'
import { contractTypeLabels } from '@/utils/format'
import Icon from '@/components/ui/Icon.vue'

withDefaults(defineProps<{ mode?: 'dropdown' | 'block' }>(), { mode: 'dropdown' })

const { t } = useI18n()
const router = useRouter()

const keyword = ref('')
const open = ref(false)
const activeIndex = ref(-1)
const root = ref<HTMLElement | null>(null)

onClickOutside(root, () => (open.value = false))

// ===== Data: laws / templates fetched once in full, filtered on the client =====
const { list: allLaws } = useApiList(qk.knowledge.laws(), () => fetchLaws(), { staleTime: 5 * 60_000 })
const { list: allTemplates } = useApiList(qk.knowledge.templates(), () => fetchTemplates(), { staleTime: 5 * 60_000 })

// ===== Data: contracts use the backend keyword query =====
const contractHits = ref<Contract[]>([])
let requestSeq = 0
const searchContracts = useDebounceFn(async (kw: string) => {
  const seq = ++requestSeq
  if (!kw) {
    contractHits.value = []
    return
  }
  try {
    const res = await fetchContracts({ keyword: kw })
    if (seq === requestSeq) contractHits.value = res
  } catch {
    if (seq === requestSeq) contractHits.value = []
  }
}, 250)

watch(keyword, (v) => {
  open.value = true
  activeIndex.value = -1
  searchContracts(v.trim())
})

const kw = computed(() => keyword.value.trim().toLowerCase())

const lawHits = computed<LawRegulation[]>(() => {
  if (!kw.value) return []
  return (allLaws.value ?? []).filter(
    (l) => l.title.toLowerCase().includes(kw.value) || l.content.toLowerCase().includes(kw.value),
  )
})

const templateHits = computed<ContractTemplate[]>(() => {
  if (!kw.value) return []
  return (allTemplates.value ?? []).filter(
    (tpl) => tpl.name.toLowerCase().includes(kw.value) || tpl.content.toLowerCase().includes(kw.value),
  )
})

interface Suggestion {
  key: string
  title: string
  meta: string
  to: string
}

interface SuggestGroup {
  key: string
  label: string
  count: number
  items: Suggestion[]
  allTo: string
  allLabel: string
}

const groups = computed<SuggestGroup[]>(() => {
  const list: SuggestGroup[] = []
  if (contractHits.value.length) {
    list.push({
      key: 'contract',
      label: t('search.groupContracts'),
      count: contractHits.value.length,
      items: contractHits.value.slice(0, 4).map((c) => ({
        key: `c-${c.id}`,
        title: c.title,
        meta: `${c.contractNo} · ${c.counterparty?.name ?? '-'}`,
        to: `/contracts/${c.id}`,
      })),
      allTo: '/contracts',
      allLabel: t('search.viewIn', { scope: t('menu.contracts') }),
    })
  }
  if (lawHits.value.length) {
    list.push({
      key: 'law',
      label: t('search.groupLaws'),
      count: lawHits.value.length,
      items: lawHits.value.slice(0, 4).map((l) => ({
        key: `l-${l.id}`,
        title: l.title,
        meta: l.sourceRef || (l.docType === 'case' ? t('knowledge.laws.typeCaseShort') : t('knowledge.laws.typeLaw')),
        to: '/knowledge/laws',
      })),
      allTo: '/knowledge/laws',
      allLabel: t('search.viewIn', { scope: t('menu.laws') }),
    })
  }
  if (templateHits.value.length) {
    list.push({
      key: 'template',
      label: t('search.groupTemplates'),
      count: templateHits.value.length,
      items: templateHits.value.slice(0, 4).map((tpl) => ({
        key: `t-${tpl.id}`,
        title: tpl.name,
        meta: contractTypeLabels[tpl.contractType] ?? tpl.contractType,
        to: '/knowledge/templates',
      })),
      allTo: '/knowledge/templates',
      allLabel: t('search.viewIn', { scope: t('menu.templates') }),
    })
  }
  return list
})

/** Flatten the suggestion list for keyboard up/down selection */
const flatItems = computed(() => groups.value.flatMap((g) => g.items))

function move(delta: number) {
  const n = flatItems.value.length
  if (!n) return
  open.value = true
  activeIndex.value = (activeIndex.value + delta + n) % n
}

function go(to: string) {
  open.value = false
  keyword.value = ''
  router.push(to)
}

function onEnter() {
  const item = flatItems.value[activeIndex.value]
  if (item) {
    go(item.to)
    return
  }
  submitAll()
}

function submitAll() {
  const q = keyword.value.trim()
  if (!q) return
  open.value = false
  keyword.value = ''
  router.push({ path: '/search', query: { q } })
}

/** Jump to the matching list page with the keyword (the list page reads the query to initialize the search) */
function goList(group: SuggestGroup) {
  const q = keyword.value.trim()
  if (!q) return
  open.value = false
  keyword.value = ''
  router.push({ path: group.allTo, query: { q } })
}
</script>

<template>
  <div ref="root" class="relative w-full" @keydown.esc="open = false">
    <!-- Input row -->
    <div
      class="flex h-8 items-center gap-2 rounded-ctl border bg-surface px-2.5 transition-colors"
      :class="open ? 'border-accent' : 'border-line hover:border-control'"
    >
      <Icon name="search" :size="14" class="text-ink-faint" />
      <input
        v-model="keyword"
        type="search"
        class="w-full bg-transparent text-body text-ink outline-none placeholder:text-ink-faint"
        :placeholder="t('search.placeholder')"
        :aria-label="t('search.placeholder')"
        @focus="open = true"
        @keydown.enter.prevent="onEnter"
        @keydown.down.prevent="move(1)"
        @keydown.up.prevent="move(-1)"
      />
      <button
        v-if="keyword"
        type="button"
        class="rounded p-0.5 text-ink-faint transition-colors hover:text-ink"
        :aria-label="t('common.close')"
        @click="keyword = ''"
      >
        <Icon name="x" :size="13" />
      </button>
    </div>

    <!-- Suggestion dropdown -->
    <div
      v-if="open && keyword.trim() && groups.length"
      class="z-50 max-h-[70vh] overflow-y-auto rounded-card border border-line bg-surface p-1 shadow-float"
      :class="mode === 'block' ? 'relative mt-2 max-h-none' : 'absolute left-0 right-0 mt-1'"
    >
      <div v-for="group in groups" :key="group.key" class="mb-1 last:mb-0">
        <p class="px-2 pb-1 pt-1.5 text-meta font-medium text-ink-faint">
          {{ group.label }} · {{ t('common.totalCount', { total: group.count }) }}
        </p>
        <button
          v-for="item in group.items"
          :key="item.key"
          type="button"
          class="flex w-full items-center gap-2 rounded-ctl px-2 py-1.5 text-left transition-colors hover:bg-raised"
          :class="flatItems[activeIndex] === item ? 'bg-raised' : ''"
          @click="go(item.to)"
          @mouseenter="activeIndex = flatItems.indexOf(item)"
        >
          <Icon
            :name="group.key === 'contract' ? 'file-text' : group.key === 'law' ? 'scale' : 'book-open'"
            :size="13"
            class="text-ink-faint"
          />
          <span class="min-w-0 flex-1">
            <span class="block truncate text-body text-ink">{{ item.title }}</span>
            <span class="block truncate text-meta text-ink-faint">{{ item.meta }}</span>
          </span>
        </button>
        <button
          type="button"
          class="flex w-full items-center gap-1.5 rounded-ctl px-2 py-1.5 text-left text-meta text-accent transition-colors hover:bg-raised"
          @click="goList(group)"
        >
          {{ group.allLabel }}
          <Icon name="arrow-right" :size="12" />
        </button>
      </div>

      <button
        type="button"
        class="flex w-full items-center gap-1.5 border-t border-line px-2 py-2 text-left text-meta text-accent transition-colors hover:bg-raised"
        @click="submitAll"
      >
        {{ t('search.viewAllResults') }}
        <Icon name="arrow-right" :size="12" />
      </button>
    </div>
  </div>
</template>

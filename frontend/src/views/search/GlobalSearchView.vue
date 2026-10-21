<script setup lang="ts">
/**
 * Global search results page: a single search across contracts / the law library / the enterprise template library.
 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { fetchContracts } from '@/api/contracts'
import { fetchLaws, fetchTemplates } from '@/api/knowledge'
import { qk } from '@/api/queryKeys'
import { useApiList } from '@/composables/useApiQuery'
import type { Contract, ContractTemplate, LawRegulation } from '@/types'
import { contractTypeLabels, formatDateTime } from '@/utils/format'
import PageHeader from '@/components/ui/PageHeader.vue'
import Icon from '@/components/ui/Icon.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const q = computed(() => String(route.query.q ?? '').trim())
const kw = computed(() => q.value.toLowerCase())

const { list: contracts, loading } = useApiList<Contract>(
  computed(() => qk.contracts.list({ keyword: q.value })),
  () => fetchContracts({ keyword: q.value }),
)

const { list: laws } = useApiList<LawRegulation>(qk.knowledge.laws(), () => fetchLaws())
const { list: templates } = useApiList<ContractTemplate>(qk.knowledge.templates(), () => fetchTemplates())

const lawHits = computed(() =>
  kw.value
    ? laws.value.filter((l) => l.title.toLowerCase().includes(kw.value) || l.content.toLowerCase().includes(kw.value))
    : [],
)
const templateHits = computed(() =>
  kw.value
    ? templates.value.filter((tpl) => tpl.name.toLowerCase().includes(kw.value) || tpl.content.toLowerCase().includes(kw.value))
    : [],
)

const total = computed(() => contracts.value.length + lawHits.value.length + templateHits.value.length)
const hasQuery = computed(() => q.value.length > 0)
</script>

<template>
  <div>
    <PageHeader :title="t('search.title')" :description="t('search.description', { q: q || '-' })">
      <template #actions>
        <button
          class="inline-flex items-center gap-1.5 text-sm text-ink-muted transition-colors hover:text-accent"
          @click="router.back()"
        >
          <Icon name="arrow-left" :size="14" /> {{ t('common.back') }}
        </button>
      </template>
    </PageHeader>

    <p v-if="hasQuery" class="mb-4 text-body text-ink-muted">
      {{ t('search.resultCount', { n: total }) }}
    </p>

    <div v-if="!hasQuery" class="rounded-card border border-line bg-surface p-8 text-center text-body text-ink-muted">
      {{ t('search.hint') }}
    </div>

    <p
      v-else-if="!loading && total === 0"
      class="rounded-card border border-line bg-surface p-8 text-center text-body text-ink-muted"
    >
      {{ t('search.noResult', { q }) }}
    </p>

    <div v-else class="space-y-5">
      <!-- Contracts -->
      <section v-if="contracts.length" class="rounded-card border border-line bg-surface">
        <header class="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          <h2 class="text-section text-ink">
            {{ t('menu.contracts') }}
            <span class="ml-1 text-meta font-normal text-ink-faint">{{ contracts.length }}</span>
          </h2>
          <router-link
            :to="{ path: '/contracts', query: { q } }"
            class="inline-flex items-center gap-1 text-meta text-accent transition-colors hover:text-accent-hover"
          >
            {{ t('search.viewIn', { scope: t('menu.contracts') }) }}
            <Icon name="arrow-right" :size="12" />
          </router-link>
        </header>
        <ul class="divide-y divide-rule">
          <li v-for="c in contracts" :key="c.id">
            <router-link
              :to="`/contracts/${c.id}`"
              class="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-raised"
            >
              <Icon name="file-text" :size="15" class="text-ink-faint" />
              <span class="min-w-0 flex-1">
                <span class="block truncate text-body text-ink">{{ c.title }}</span>
                <span class="block truncate text-meta text-ink-faint">
                  {{ c.contractNo }} · {{ c.counterparty?.name ?? '-' }} · {{ formatDateTime(c.updatedAt) }}
                </span>
              </span>
              <span class="shrink-0 text-meta text-ink-faint">{{ contractTypeLabels[c.contractType] }}</span>
            </router-link>
          </li>
        </ul>
      </section>

      <!-- Laws and cases -->
      <section v-if="lawHits.length" class="rounded-card border border-line bg-surface">
        <header class="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          <h2 class="text-section text-ink">
            {{ t('menu.laws') }}
            <span class="ml-1 text-meta font-normal text-ink-faint">{{ lawHits.length }}</span>
          </h2>
          <router-link
            :to="{ path: '/knowledge/laws', query: { q } }"
            class="inline-flex items-center gap-1 text-meta text-accent transition-colors hover:text-accent-hover"
          >
            {{ t('search.viewIn', { scope: t('menu.laws') }) }}
            <Icon name="arrow-right" :size="12" />
          </router-link>
        </header>
        <ul class="divide-y divide-rule">
          <li v-for="l in lawHits" :key="l.id">
            <router-link
              :to="{ path: '/knowledge/laws', query: { q: l.title } }"
              class="flex items-start gap-3 px-4 py-3 transition-colors hover:bg-raised"
            >
              <Icon name="scale" :size="15" class="mt-0.5 text-ink-faint" />
              <span class="min-w-0 flex-1">
                <span class="block truncate text-body text-ink">{{ l.title }}</span>
                <span class="block truncate text-meta text-ink-faint">{{ l.sourceRef || '-' }}</span>
              </span>
              <span class="shrink-0 text-meta text-ink-faint">
                {{ l.docType === 'case' ? t('knowledge.laws.typeCaseShort') : t('knowledge.laws.typeLaw') }}
              </span>
            </router-link>
          </li>
        </ul>
      </section>

      <!-- Template clauses -->
      <section v-if="templateHits.length" class="rounded-card border border-line bg-surface">
        <header class="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          <h2 class="text-section text-ink">
            {{ t('menu.templates') }}
            <span class="ml-1 text-meta font-normal text-ink-faint">{{ templateHits.length }}</span>
          </h2>
          <router-link
            :to="{ path: '/knowledge/templates', query: { q } }"
            class="inline-flex items-center gap-1 text-meta text-accent transition-colors hover:text-accent-hover"
          >
            {{ t('search.viewIn', { scope: t('menu.templates') }) }}
            <Icon name="arrow-right" :size="12" />
          </router-link>
        </header>
        <ul class="divide-y divide-rule">
          <li v-for="tpl in templateHits" :key="tpl.id">
            <router-link
              :to="{ path: '/knowledge/templates', query: { q: tpl.name } }"
              class="flex items-start gap-3 px-4 py-3 transition-colors hover:bg-raised"
            >
              <Icon name="book-open" :size="15" class="mt-0.5 text-ink-faint" />
              <span class="min-w-0 flex-1">
                <span class="block truncate text-body text-ink">{{ tpl.name }}</span>
                <span class="block truncate text-meta text-ink-faint">{{ tpl.content }}</span>
              </span>
              <span class="shrink-0 text-meta text-ink-faint">{{ contractTypeLabels[tpl.contractType] }}</span>
            </router-link>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>

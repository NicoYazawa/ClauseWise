<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/ui/Icon.vue'
import BrandLogo from '@/components/ui/BrandLogo.vue'
import { useAuthStore } from '@/stores/auth'
import { fetchRuntimeInfo } from '@/api/system'
import { qk } from '@/api/queryKeys'
import { useApiDetail } from '@/composables/useApiQuery'
import { translateData } from '@/utils/i18nData'
import { navGroups, navMatches, navSingles, type NavGroup, type NavItem } from './nav'

const { t } = useI18n()
const route = useRoute()
const auth = useAuthStore()

const singles = navSingles
const groups = navGroups

const visibleGroups = computed(() => groups.filter((g) => !g.adminOnly || auth.isAdmin()))

function isActive(item: NavItem): boolean {
  return navMatches(item, route.path)
}
function groupActive(group: NavGroup): boolean {
  return group.items.some((i) => isActive(i))
}

// Sidebar footer shows the actually-active model and embedding config (auto-reflected after changing .env)
const { data: runtime } = useApiDetail(qk.system.runtimeInfo(), fetchRuntimeInfo, {
  staleTime: 5 * 60_000,
  retry: false,
})

// Two lines: one for the model, one for the embedding, so long model names are not truncated in the narrow sidebar
const modelLines = computed(() => {
  const r = runtime.value
  if (!r) {
    const unknown = t('footer.unknown')
    return {
      llm: t('footer.llmLabel', { llm: unknown }),
      emb: t('footer.embLabel', { emb: unknown }),
    }
  }
  // When the gateway alias is resolved to the real model, show the real name; if the model name already includes the vendor, do not repeat the prefix
  const llmName = r.llm.realModel ?? r.llm.model
  const llmVendor = r.llm.realProvider ?? r.llm.provider
  const llmDisplay =
    llmVendor === 'custom' || llmName.toLowerCase().startsWith(llmVendor.toLowerCase())
      ? llmName
      : `${llmVendor}:${llmName}`
  const llmText =
    r.llm.provider === '-'
      ? t('footer.unconfigured')
      : `${llmDisplay}${r.llm.configured ? '' : t('footer.unconfiguredKey')}`
  const embText =
    r.embedding.provider === '-'
      ? t('footer.unconfigured')
      : `${r.embedding.model}${r.embedding.dimensions ? ` (${r.embedding.dimensions}d)` : ''}${
          r.embedding.configured ? '' : t('footer.unconfiguredKey')
        }`
  return {
    llm: t('footer.llmLabel', { llm: llmText }),
    emb: t('footer.embLabel', { emb: embText }),
  }
})
</script>

<template>
  <div class="flex h-full flex-col">
    <!-- Product identity and scope -->
    <div class="px-4 pb-4 pt-5">
      <div class="flex items-center gap-2.5">
        <BrandLogo :size="28" />
        <div class="min-w-0 leading-tight">
          <p class="truncate text-body font-semibold text-ink">{{ t('app.name') }}</p>
          <p class="truncate text-meta text-ink-faint">{{ translateData(auth.state.user?.deptName) || t('app.tagline') }}</p>
        </div>
      </div>
    </div>

    <nav class="flex-1 overflow-y-auto px-2.5 pb-4" :aria-label="t('a11y.mainNav')">
      <router-link
        v-for="item in singles"
        :key="item.to"
        :to="item.to"
        class="nav-row group"
        :class="isActive(item) && 'nav-row-active'"
        :aria-current="isActive(item) ? 'page' : undefined"
      >
        <Icon
          :name="item.icon ?? 'info'"
          :size="16"
          :class="isActive(item) ? 'text-accent' : 'text-ink-faint group-hover:text-ink-muted'"
        />
        <span class="truncate">{{ t(item.labelKey) }}</span>
      </router-link>

      <template v-for="group in visibleGroups" :key="group.labelKey">
        <div class="mt-4 flex items-center gap-2 px-2.5">
          <Icon :name="group.icon" :size="14" :class="groupActive(group) ? 'text-accent' : 'text-ink-faint'" />
          <span class="text-meta" :class="groupActive(group) ? 'text-accent-ink' : 'text-ink-faint'">
            {{ t(group.labelKey) }}
          </span>
        </div>
        <router-link
          v-for="child in group.items"
          :key="child.to"
          :to="child.to"
          class="nav-row group pl-9"
          :class="isActive(child) && 'nav-row-active'"
          :aria-current="isActive(child) ? 'page' : undefined"
        >
          <span class="truncate">{{ t(child.labelKey) }}</span>
        </router-link>
      </template>
    </nav>

    <!-- Footer: actually-active model config (the footer role is carried by the sidebar; pages do not repeat it) -->
    <div class="border-t border-line px-4 py-3">
      <p class="text-meta leading-snug text-ink-faint break-words" :title="runtime ? `${runtime.llm.error ?? ''}${runtime.embedding.error ?? ''}` : ''">
        {{ modelLines.llm }}
      </p>
      <p class="mt-0.5 text-meta leading-snug text-ink-faint break-words" :title="runtime ? `${runtime.llm.error ?? ''}${runtime.embedding.error ?? ''}` : ''">
        {{ modelLines.emb }}
      </p>
    </div>
  </div>
</template>

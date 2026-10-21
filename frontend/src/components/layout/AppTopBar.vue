<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuPortal,
  DropdownMenuRoot,
  DropdownMenuTrigger,
} from 'reka-ui'
import { useAuthStore } from '@/stores/auth'
import { changePassword } from '@/api/system'
import { toastSuccess, toastError } from '@/plugins/toast'
import { useLocale } from '@/i18n/useLocale'
import { translateData } from '@/utils/i18nData'
import Icon from '@/components/ui/Icon.vue'
import BrandLogo from '@/components/ui/BrandLogo.vue'
import GlobalSearchBox from './GlobalSearchBox.vue'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/ui/BaseInput.vue'

const emit = defineEmits<{ openNav: [] }>()

const { t } = useI18n()
const { locale, locales, setLocale } = useLocale()
const router = useRouter()
const auth = useAuthStore()

function logout() {
  auth.logout()
  router.push('/login')
}

// ===== Change password =====
const pwdOpen = ref(false)
const pwdForm = ref({ old: '', next: '', confirm: '' })
const pwdSaving = ref(false)

function openChangePwd() {
  pwdForm.value = { old: '', next: '', confirm: '' }
  pwdOpen.value = true
}

async function submitChangePwd() {
  if (pwdForm.value.next !== pwdForm.value.confirm) {
    toastError(t('password.mismatch'))
    return
  }
  pwdSaving.value = true
  try {
    await changePassword(pwdForm.value.old, pwdForm.value.next)
    toastSuccess(t('password.success'))
    pwdOpen.value = false
  } catch (e) {
    toastError(e instanceof Error ? e.message : t('password.fail'))
  } finally {
    pwdSaving.value = false
  }
}
</script>

<template>
  <header class="sticky top-0 z-30 flex h-topbar shrink-0 items-center gap-3 border-b border-line bg-ground px-4 lg:px-6">
    <button
      class="-ml-1 rounded-ctl p-2 text-ink-muted transition-colors hover:bg-raised hover:text-ink lg:hidden"
      :aria-label="t('common.menu')"
      @click="emit('openNav')"
    >
      <Icon name="list" :size="18" />
    </button>

    <!-- On narrow screens the sidebar collapses; the brand mark is carried by the top bar -->
    <router-link to="/dashboard" class="flex items-center gap-2 lg:hidden" :aria-label="t('app.name')">
      <BrandLogo :size="24" />
      <span class="text-body font-semibold text-ink">{{ t('app.name') }}</span>
    </router-link>

    <!-- Top-bar left: global search (page title and breadcrumb are handled by the content-area PageHeader, not duplicated here) -->
    <GlobalSearchBox />

    <div class="ml-auto flex items-center gap-2">
      <!-- Language switch: segmented control, 28px tall, same height as other top-bar controls -->
      <div class="flex items-center gap-0.5 rounded-ctl bg-raised p-0.5">
        <button
          v-for="l in locales"
          :key="l"
          type="button"
          class="h-6 rounded-[4px] px-2 text-meta transition-colors"
          :class="locale === l ? 'bg-surface font-medium text-ink shadow-card' : 'text-ink-muted hover:text-ink'"
          @click="setLocale(l)"
        >
          {{ l === 'zh-CN' ? '中' : 'EN' }}
        </button>
      </div>

      <div class="self-stretch w-px bg-line" aria-hidden="true" />

      <DropdownMenuRoot>
        <DropdownMenuTrigger as-child>
          <button
            class="flex items-center gap-2 rounded-ctl py-1.5 pl-1.5 pr-2 transition-colors hover:bg-raised"
            :aria-label="auth.state.user?.realName ?? t('user.logout')"
          >
            <span
              class="flex h-7 w-7 items-center justify-center rounded-full bg-accent-soft text-meta font-semibold text-accent-ink"
            >
              {{ auth.state.user?.realName?.slice(0, 1) ?? '?' }}
            </span>
            <span class="hidden leading-tight md:block">
              <span class="block text-meta font-medium text-ink">{{ auth.state.user?.realName }}</span>
              <span class="block text-meta text-ink-faint">{{ auth.roleDisplayName() }}</span>
            </span>
            <Icon name="chevron-down" :size="13" class="text-ink-faint" />
          </button>
        </DropdownMenuTrigger>

        <DropdownMenuPortal>
          <DropdownMenuContent
            align="end"
            :side-offset="6"
            class="z-50 w-56 rounded-card border border-line bg-surface p-1 shadow-float will-change-transform
              data-[state=open]:animate-[menu-in_140ms_cubic-bezier(0.22,1,0.36,1)]"
          >
            <div class="px-2.5 py-2">
              <p class="text-body font-medium text-ink">{{ auth.state.user?.realName }}</p>
              <p class="text-meta text-ink-faint">{{ translateData(auth.state.user?.deptName) }} · {{ translateData(auth.state.user?.title) }}</p>
              <span class="pill-accent mt-1.5">{{ auth.roleDisplayName() }}</span>
            </div>
            <div class="my-1 h-px bg-line" />
            <DropdownMenuItem
              class="flex cursor-pointer items-center gap-2 rounded-ctl px-2.5 py-2 text-body text-ink-muted outline-none
                data-[highlighted]:bg-raised data-[highlighted]:text-ink"
              @select="openChangePwd"
            >
              <Icon name="lock" :size="14" /> {{ t('user.changePassword') }}
            </DropdownMenuItem>
            <DropdownMenuItem
              class="flex cursor-pointer items-center gap-2 rounded-ctl px-2.5 py-2 text-body text-ink-muted outline-none
                data-[highlighted]:bg-raised data-[highlighted]:text-ink"
              @select="logout"
            >
              <Icon name="logout" :size="14" /> {{ t('user.logout') }}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenuPortal>
      </DropdownMenuRoot>
    </div>

    <BaseModal :open="pwdOpen" :title="t('password.title')" width="max-w-md" @close="pwdOpen = false">
      <div class="space-y-4">
        <BaseInput v-model="pwdForm.old" :label="t('password.old')" type="password" :placeholder="t('password.oldPlaceholder')" />
        <BaseInput v-model="pwdForm.next" :label="t('password.new')" type="password" :placeholder="t('password.newPlaceholder')" />
        <BaseInput v-model="pwdForm.confirm" :label="t('password.confirm')" type="password" :placeholder="t('password.confirmPlaceholder')" />
        <div class="well p-3 text-meta leading-relaxed text-ink-muted">
          {{ t('password.notice') }}
        </div>
      </div>
      <template #footer>
        <BaseButton variant="secondary" @click="pwdOpen = false">{{ t('common.cancel') }}</BaseButton>
        <BaseButton icon="lock" :loading="pwdSaving" @click="submitChangePwd">{{ t('common.confirmModify') }}</BaseButton>
      </template>
    </BaseModal>
  </header>
</template>

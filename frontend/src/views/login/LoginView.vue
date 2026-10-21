<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { changePassword, fetchPresetAccounts, login, passwordMeetsPolicy, type PresetAccount } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import Icon from '@/components/ui/Icon.vue'
import BrandLogo from '@/components/ui/BrandLogo.vue'
import { toastError } from '@/plugins/toast'
import { translateData } from '@/utils/i18nData'

const { t } = useI18n()
const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const username = ref('')
const password = ref('')
const loading = ref(false)
const errorMsg = ref('')

const pendingToken = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const successMsg = ref('')

// Preset (demo) accounts: shown only when the backend switch is on; click to auto-fill the username and shared password
const presetAccounts = ref<PresetAccount[]>([])
const presetPassword = ref('')

// Previously persisted forced-change credentials cannot enter the application.
if (auth.state.user?.mustChangePassword) auth.logout()

function clearCredentials() {
  pendingToken.value = ''
  username.value = ''
  password.value = ''
  newPassword.value = ''
  confirmPassword.value = ''
}
onUnmounted(clearCredentials)

function fillPreset(account: PresetAccount) {
  username.value = account.username
  password.value = presetPassword.value
  errorMsg.value = ''
}

onMounted(async () => {
  try {
    const info = await fetchPresetAccounts()
    if (!info.enabled) return
    presetPassword.value = info.password ?? ''
    presetAccounts.value = info.accounts
  } catch {
    // An unavailable demo list does not block normal-account login
  }
})

async function finishPasswordChange() {
  if (!passwordMeetsPolicy(newPassword.value)) {
    errorMsg.value = t('password.requirements')
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    errorMsg.value = t('password.mismatch')
    return
  }
  loading.value = true
  errorMsg.value = ''
  try {
    await changePassword(password.value, newPassword.value, pendingToken.value)
    clearCredentials()
    auth.logout()
    successMsg.value = t('password.success')
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : t('password.fail')
  } finally {
    loading.value = false
  }
}

async function onSubmit() {
  if (pendingToken.value) return finishPasswordChange()
  successMsg.value = ''
  if (!username.value || !password.value) {
    errorMsg.value = t('login.errorRequired')
    return
  }
  loading.value = true
  errorMsg.value = ''
  try {
    const user = await login({ username: username.value, password: password.value })
    if (user.mustChangePassword) {
      auth.logout()
      pendingToken.value = user.token
      return
    }
    password.value = ''
    auth.setUser(user)
    router.push((route.query.redirect as string) ?? '/dashboard')
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : t('login.errorFailed')
    toastError(errorMsg.value)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="min-h-screen flex bg-surface">
    <!-- Brand side: most area is light-toned; full intensity is reserved for the mark -->
    <div class="hidden lg:flex flex-col justify-between w-[46%] p-12 bg-accent-soft">
      <div class="flex items-center gap-2.5">
        <BrandLogo :size="34" />
        <div>
          <p class="text-section text-ink">{{ t('login.brandName') }}</p>
          <p class="text-meta text-ink-muted">{{ t('login.brandTagline') }}</p>
        </div>
      </div>

      <div>
        <h1 class="text-[28px] font-semibold leading-snug text-ink whitespace-pre-line">{{ t('login.heroTitle') }}</h1>
        <p class="mt-4 text-body text-ink-muted leading-relaxed max-w-md">
          {{ t('login.heroDesc') }}
        </p>

        <div class="mt-8 grid grid-cols-1 gap-3 max-w-md">
          <div class="flex items-start gap-3 rounded-card border border-line bg-surface p-4">
            <Icon name="zap" :size="18" class="mt-0.5 text-accent" />
            <div>
              <p class="text-body font-semibold text-ink">{{ t('login.feature1Title') }}</p>
              <p class="mt-0.5 text-meta text-ink-muted">{{ t('login.feature1Desc') }}</p>
            </div>
          </div>
          <div class="flex items-start gap-3 rounded-card border border-line bg-surface p-4">
            <Icon name="shield-check" :size="18" class="mt-0.5 text-accent" />
            <div>
              <p class="text-body font-semibold text-ink">{{ t('login.feature2Title') }}</p>
              <p class="mt-0.5 text-meta text-ink-muted">{{ t('login.feature2Desc') }}</p>
            </div>
          </div>
          <div class="flex items-start gap-3 rounded-card border border-line bg-surface p-4">
            <Icon name="database" :size="18" class="mt-0.5 text-accent" />
            <div>
              <p class="text-body font-semibold text-ink">{{ t('login.feature3Title') }}</p>
              <p class="mt-0.5 text-meta text-ink-muted">{{ t('login.feature3Desc') }}</p>
            </div>
          </div>
        </div>
      </div>

      <p class="text-meta text-ink-faint">{{ t('login.copyright') }}</p>
    </div>

    <!-- Right login panel -->
    <div class="flex flex-1 items-center justify-center p-6">
      <div class="w-full max-w-sm">
        <div class="lg:hidden flex items-center gap-2 mb-8">
          <BrandLogo :size="30" />
          <p class="text-lg font-bold text-ink">{{ t('login.brandName') }}</p>
        </div>

        <h2 class="text-section text-ink">{{ pendingToken ? t('login.changeRequiredTitle') : t('login.welcome') }}</h2>
        <p class="mt-1.5 text-body text-ink-muted">{{ pendingToken ? t('login.changeRequiredDesc') : t('login.welcomeDesc') }}</p>

        <p v-if="successMsg" role="status" class="mt-4 text-body text-success-600">{{ successMsg }}</p>
        <form class="mt-8 space-y-4" @submit.prevent="onSubmit">
          <div v-if="!pendingToken">
            <label class="label" for="username">{{ t('login.username') }}</label>
            <input id="username" v-model="username" class="input" :placeholder="t('login.usernamePlaceholder')" autocomplete="username" />
          </div>
          <div v-if="!pendingToken">
            <label class="label" for="password">{{ t('login.password') }}</label>
            <input id="password" v-model="password" type="password" class="input" :placeholder="t('login.passwordPlaceholder')" autocomplete="current-password" />
          </div>
          <template v-if="pendingToken">
            <div>
              <label class="label" for="new-password">{{ t('password.new') }}</label>
              <input id="new-password" v-model="newPassword" type="password" class="input" :placeholder="t('password.newPlaceholder')" autocomplete="new-password" required />
            </div>
            <div>
              <label class="label" for="confirm-password">{{ t('password.confirm') }}</label>
              <input id="confirm-password" v-model="confirmPassword" type="password" class="input" :placeholder="t('password.confirmPlaceholder')" autocomplete="new-password" required />
            </div>
            <p class="text-meta text-ink-muted">{{ t('password.requirements') }}</p>
          </template>
          <p v-if="errorMsg" role="alert" class="flex items-center gap-1.5 text-body text-danger-600">
            <Icon name="alert-triangle" :size="14" />{{ errorMsg }}
          </p>
          <button
            type="submit"
            class="btn-primary h-10 w-full"
            :disabled="loading"
          >
            <Icon v-if="loading" name="refresh" :size="14" class="animate-spin" />
            {{ loading ? t('login.submitting') : pendingToken ? t('common.confirmModify') : t('login.submit') }}
          </button>
        </form>

        <button v-if="pendingToken" type="button" class="mt-4 text-body text-ink-muted hover:text-ink" :disabled="loading" @click="clearCredentials(); errorMsg = ''">{{ t('login.backToLogin') }}</button>

        <!-- Preset (demo) accounts: not rendered when the backend switch is off -->
        <div v-if="!pendingToken && presetAccounts.length" class="mt-8 border-t border-line pt-5">
          <p class="text-meta font-semibold text-ink">{{ t('login.presetTitle') }}</p>
          <p class="mt-1 text-[11px] text-ink-faint">{{ t('login.presetHint', { password: presetPassword }) }}</p>
          <div class="mt-3 grid grid-cols-2 gap-1.5">
            <button
              v-for="account in presetAccounts"
              :key="account.username"
              type="button"
              class="flex w-full flex-col items-start rounded-card border border-line bg-surface px-2.5 py-2 text-left transition-colors hover:border-accent hover:bg-accent-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              @click="fillPreset(account)"
            >
              <span class="w-full truncate text-meta font-medium text-ink">{{ account.realName }}</span>
              <span class="w-full truncate text-[11px] text-ink-muted">
                {{ translateData(account.roleName) }} · {{ account.username }}
              </span>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

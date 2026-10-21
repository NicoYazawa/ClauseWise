import { computed } from 'vue'
import { i18n, SUPPORTED_LOCALES, type AppLocale } from './index'

const STORAGE_KEY = 'cw-locale'

/**
 * Reactive accessor for the active locale.
 * Setting it persists to localStorage and syncs <html lang>.
 */
export function useLocale() {
  const locale = computed<AppLocale>({
    get: () => i18n.global.locale.value as AppLocale,
    set: (val) => {
      i18n.global.locale.value = val
      localStorage.setItem(STORAGE_KEY, val)
      document.documentElement.lang = val === 'zh-CN' ? 'zh-CN' : 'en'
    },
  })

  return {
    locale,
    locales: SUPPORTED_LOCALES,
    setLocale: (v: AppLocale) => {
      locale.value = v
    },
  }
}

import { createI18n } from 'vue-i18n'
import zhCN from './locales/zh-CN'
import enUS from './locales/en-US'

export type AppLocale = 'zh-CN' | 'en-US'
export const SUPPORTED_LOCALES: AppLocale[] = ['zh-CN', 'en-US']

const STORAGE_KEY = 'cw-locale'

function detectLocale(): AppLocale {
  const saved = localStorage.getItem(STORAGE_KEY) as AppLocale | null
  if (saved && (SUPPORTED_LOCALES as string[]).includes(saved)) return saved
  if (navigator.language.toLowerCase().startsWith('en')) return 'en-US'
  return 'zh-CN'
}

export const i18n = createI18n({
  legacy: false,
  locale: detectLocale(),
  fallbackLocale: 'zh-CN',
  messages: { 'zh-CN': zhCN, 'en-US': enUS },
})

// Sync initial <html lang> for accessibility / SEO.
document.documentElement.lang = i18n.global.locale.value === 'zh-CN' ? 'zh-CN' : 'en'

export default i18n

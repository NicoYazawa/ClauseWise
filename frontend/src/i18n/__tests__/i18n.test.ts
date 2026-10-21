import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * i18n 实例在模块加载时即完成 locale 探测，因此每个用例都要 resetModules 后动态 import，
 * 以覆盖 detectLocale 的三条分支（保存值 / 浏览器语言 / 默认中文）。
 */
describe('detectLocale 语言探测', () => {
  beforeEach(() => {
    vi.resetModules()
    localStorage.clear()
    Object.defineProperty(navigator, 'language', { value: 'zh-CN', configurable: true })
  })

  afterEach(() => {
    localStorage.clear()
  })

  it('优先使用 localStorage 中受支持的语言', async () => {
    localStorage.setItem('cw-locale', 'en-US')
    const mod = await import('@/i18n')
    expect(mod.i18n.global.locale.value).toBe('en-US')
    expect(document.documentElement.lang).toBe('en')
  })

  it('保存值不受支持时回退到浏览器语言', async () => {
    localStorage.setItem('cw-locale', 'fr-FR')
    Object.defineProperty(navigator, 'language', { value: 'en-GB', configurable: true })
    const mod = await import('@/i18n')
    expect(mod.i18n.global.locale.value).toBe('en-US')
  })

  it('无保存值时按浏览器语言判断，中文为默认', async () => {
    const mod = await import('@/i18n')
    expect(mod.i18n.global.locale.value).toBe('zh-CN')
    expect(document.documentElement.lang).toBe('zh-CN')
    expect(mod.SUPPORTED_LOCALES).toEqual(['zh-CN', 'en-US'])
  })
})

describe('useLocale 语言切换', () => {
  beforeEach(async () => {
    vi.resetModules()
    localStorage.clear()
  })

  it('setLocale 同步 i18n、localStorage 与 <html lang>', async () => {
    const { useLocale } = await import('@/i18n/useLocale')
    const { i18n } = await import('@/i18n')
    const { locale, locales, setLocale } = useLocale()

    expect(locales).toEqual(['zh-CN', 'en-US'])
    setLocale('en-US')
    expect(locale.value).toBe('en-US')
    expect(i18n.global.locale.value).toBe('en-US')
    expect(localStorage.getItem('cw-locale')).toBe('en-US')
    expect(document.documentElement.lang).toBe('en')

    setLocale('zh-CN')
    expect(locale.value).toBe('zh-CN')
    expect(localStorage.getItem('cw-locale')).toBe('zh-CN')
    expect(document.documentElement.lang).toBe('zh-CN')
  })

  it('直接给 locale 赋值同样持久化', async () => {
    const { useLocale } = await import('@/i18n/useLocale')
    const { locale } = useLocale()
    locale.value = 'en-US'
    expect(localStorage.getItem('cw-locale')).toBe('en-US')
    expect(document.documentElement.lang).toBe('en')
  })
})

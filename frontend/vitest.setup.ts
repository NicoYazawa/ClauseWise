// Vitest setup: guarantee web storage/global APIs exist before app modules run
// (some environments do not register localStorage on globalThis even under happy-dom).
if (typeof globalThis.localStorage === 'undefined') {
  const store = new Map<string, string>()
  const shim = {
    getItem: (key: string) => (store.has(key) ? store.get(key)! : null),
    setItem: (key: string, value: string) => {
      store.set(key, String(value))
    },
    removeItem: (key: string) => {
      store.delete(key)
    },
    clear: () => store.clear(),
    key: (index: number) => [...store.keys()][index] ?? null,
    get length() {
      return store.size
    },
  }
  Object.defineProperty(globalThis, 'localStorage', { value: shim, configurable: true, writable: true })
}
if (typeof globalThis.navigator === 'undefined') {
  Object.defineProperty(globalThis, 'navigator', {
    value: { language: 'zh-CN' },
    configurable: true,
    writable: true,
  })
}

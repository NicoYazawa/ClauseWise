import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient } from '@tanstack/vue-query'

const require = createRequire(import.meta.url)
function load(relative, dependencies, localStorage) {
  const source = readFileSync(new URL(relative, import.meta.url), 'utf8')
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
  const exports = {}
  vm.runInNewContext(compiled, {
    exports, localStorage, TextEncoder,
    require: name => name in dependencies ? dependencies[name] : require(name),
  })
  return exports
}
function setup() {
  const storage = new Map()
  const localStorage = { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) }
  const queryClient = new QueryClient()
  const module = load('../src/stores/auth.ts', {
    '@/api/http': { AUTH_STORAGE_KEY: 'cc_auth' },
    '@/api/queryClient': { queryClient },
    '@/utils/i18nData': { translateData: value => value },
  }, localStorage)
  setActivePinia(createPinia())
  return { auth: module.useAuthStore(), queryClient, storage }
}
const user = (id, mustChangePassword = false) => ({ id, token: `token-${id}`, username: `user-${id}`, roles: [], mustChangePassword })

test('logging out removes prior account query and mutation results', () => {
  const { auth, queryClient, storage } = setup()
  auth.setUser(user(1))
  queryClient.setQueryData(['contracts'], ['PRIVATE'])
  auth.logout()
  assert.equal(queryClient.getQueryData(['contracts']), undefined)
  assert.equal(storage.has('cc_auth'), false)
})

test('changing account identity removes cached contracts before new account data loads', () => {
  const { auth, queryClient } = setup()
  auth.setUser(user(1))
  queryClient.setQueryData(['contracts'], ['PRIVATE'])
  auth.setUser(user(2))
  assert.equal(queryClient.getQueryData(['contracts']), undefined)
})

test('temporary forced-change credentials are never persisted by the auth store', () => {
  const { auth, storage } = setup()
  auth.setUser(user(1, true))
  assert.equal(storage.has('cc_auth'), false)
})

test('password validation counts Unicode characters and enforces the UTF-8 bcrypt byte limit', () => {
  const { passwordMeetsPolicy } = load('../src/api/auth.ts', { '@/api/http': { http: {} } })
  assert.equal(passwordMeetsPolicy('a'.repeat(11)), false)
  assert.equal(passwordMeetsPolicy('a'.repeat(12)), true)
  assert.equal(passwordMeetsPolicy('密'.repeat(24)), true)
  assert.equal(passwordMeetsPolicy('密'.repeat(25)), false)
  assert.equal(passwordMeetsPolicy('🔐'.repeat(11)), false)
  assert.equal(passwordMeetsPolicy('a'.repeat(73)), false)
})

test('forced password change sends its in-memory token explicitly', async () => {
  const calls = []
  const { changePassword } = load('../src/api/auth.ts', { '@/api/http': { http: { post: async (...args) => calls.push(args) } } })
  await changePassword('old', 'new-password-long', 'temporary-token')
  assert.equal(calls[0][2].headers.Authorization, 'Bearer temporary-token')
})

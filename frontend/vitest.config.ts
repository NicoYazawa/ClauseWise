import { fileURLToPath } from 'node:url'

import vue from '@vitejs/plugin-vue'

import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      '@test': fileURLToPath(new URL('./tests', import.meta.url)),
    },
  },
  test: {
    include: ['src/**/__tests__/**/*.test.ts'],
    environment: 'happy-dom',
    setupFiles: ['./vitest.setup.ts'],
    // happy-dom 在卸载弹窗时取消 motion 动画会抛出 AbortError，属于环境噪音，不应让测试失败
    onUnhandledError: (error) => !/animation was canceled/i.test(String((error as Error)?.message ?? '')),
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json-summary'],
      include: ['src/**/*.{ts,vue}'],
      exclude: ['src/**/__tests__/**', 'src/env.d.ts'],
      // 覆盖率门槛：行与分支都必须 ≥ 90%
      thresholds: { lines: 90, branches: 90 },
    },
  },
})

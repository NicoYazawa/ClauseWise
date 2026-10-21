import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    open: false,
    proxy: {
      // 开发期代理到 FastAPI 后端（同源部署时由 Nginx 托管 dist）
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        // Vite 8（Rolldown）不再接受对象式 manualChunks，改用 advancedChunks 分组
        advancedChunks: {
          groups: [
            {
              name: 'echarts',
              test: /[\\/]node_modules[\\/](echarts|zrender)[\\/]/,
            },
          ],
        },
      },
    },
  },
})
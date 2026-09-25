import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

/**
 * 开发态把 /api 代理到本地 FastAPI（默认 17800）。
 *
 * 这样开发时前端与后端同源，不需要在浏览器里处理 CORS；
 * 打包态由 Tauri 启动 Python sidecar，并通过 __PHARMRELATE_API__ 注入真实地址。
 */
const BACKEND_ORIGIN = process.env.PHARMRELATE_API_ORIGIN ?? 'http://127.0.0.1:17800'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: BACKEND_ORIGIN,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})

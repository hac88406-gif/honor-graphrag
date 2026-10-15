import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发期把 /api 代理到后端 uvicorn（默认 8000），避免前端自己处理跨域。
// 生产/演示时由 vite build 产出静态文件，交给任意静态服务器（或后端直接挂载）。
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})

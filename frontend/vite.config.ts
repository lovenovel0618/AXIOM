import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: { '/health': { target: process.env.AXIOM_WEB_TARGET ?? 'http://127.0.0.1:18000' } },
  },
})

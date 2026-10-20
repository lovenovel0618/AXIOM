import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const target = process.env.AXIOM_WEB_TARGET ?? 'http://127.0.0.1:18000'

export default defineConfig({
  plugins: [vue()],
  server: {
    allowedHosts: ['frontend'],
    proxy: { '/health': { target }, '/auth': { target }, '/api': { target }, '/storage': { target } },
  },
})

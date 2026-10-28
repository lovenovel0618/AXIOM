import { mergeConfig } from 'vite'
import { defineConfig } from 'vitest/config'
import viteConfig from './vite.config.ts'

export default mergeConfig(viteConfig, defineConfig({
  test: {
    coverage: {
      provider: 'v8',
      include: ['src/**/*.ts', 'src/**/*.vue'],
      reportsDirectory: 'coverage',
      reporter: ['text-summary', ['lcov', { projectRoot: '..' }], 'json-summary'],
    },
  },
}))

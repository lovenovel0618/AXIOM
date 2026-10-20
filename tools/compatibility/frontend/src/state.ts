import { defineStore } from 'pinia'

export const useCompatibilityStore = defineStore('compatibility', {
  state: () => ({ result: 0 }),
  actions: {
    evaluateLinear(x: number): void {
      this.result = 2 * x + 1
    },
  },
})

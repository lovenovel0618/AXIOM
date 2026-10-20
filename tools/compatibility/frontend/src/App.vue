<script setup lang="ts">
import { useCompatibilityStore } from './state'

const state = useCompatibilityStore()
state.evaluateLinear(3)
</script>

<template>
  <main>
    <h1>AXIOM T02 相容性驗證</h1>
    <p>固定測試結果：{{ state.result }}</p>
    <p>此畫面只供技術驗證。</p>
  </main>
</template>

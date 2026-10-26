<script setup lang="ts">
/**
 * 候選比較：釘選至多四條候選並排，只顯示契約已提供的欄位。
 * 凍結前不查詢 final_test；此處一律標示「尚未評估」，不推測分數。
 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { MAX_COMPARISON, type Candidate, type EquationVersion, type FitRun, type ValidationStatus } from '../api/candidates'
import { formulaComplexity, parameterPrecision, renderDomain, renderFormula } from '../lib/formula'

const MAX_PINNED = MAX_COMPARISON

const props = defineProps<{
  candidates: Candidate[]
  pinned: string[]
  equations: Record<string, EquationVersion>
  fits: Record<string, FitRun>
  detailsLoading: boolean
  /** 來源 SEARCH 任務；提供時可開啟單一候選的公式工作區。 */
  runId?: string
}>()

const emit = defineEmits<{ toggle: [id: string] }>()

const statusLabels: Record<ValidationStatus, string> = {
  NOT_RUN: '尚未執行',
  PENDING: '進行中',
  FINISHED: '已完成',
  INVALID: '無效',
}

const pinnedRows = computed<Candidate[]>(() =>
  props.pinned
    .map((id) => props.candidates.find((row) => row.id === id))
    .filter((row): row is Candidate => row !== undefined),
)

const isFull = computed<boolean>(() => props.pinned.length >= MAX_PINNED)

function formulaFor(candidate: Candidate): string {
  const equation = props.equations[candidate.equation_version_id]
  return equation === undefined ? '載入中…' : renderFormula(equation.dsl.root)
}

function domainFor(candidate: Candidate): string {
  const equation = props.equations[candidate.equation_version_id]
  return equation === undefined ? '載入中…' : renderDomain(equation.dsl.domain)
}

function complexityFor(candidate: Candidate): number | null {
  const equation = props.equations[candidate.equation_version_id]
  return equation === undefined ? null : formulaComplexity(equation.dsl.root)
}

function fitFor(candidate: Candidate): FitRun | undefined {
  const fitId = candidate.fit_run_ids[0]
  return fitId === undefined ? undefined : props.fits[fitId]
}

function parametersFor(candidate: Candidate): string {
  const fit = fitFor(candidate)
  if (fit === undefined) return '載入中…'
  const entries = Object.entries(fit.parameters)
  return entries.length === 0 ? '無參數' : entries.map(([name, value]) => `${name} = ${value}`).join('；')
}

function precisionFor(candidate: Candidate): number | null {
  const fit = fitFor(candidate)
  return fit === undefined ? null : parameterPrecision(fit.parameters)
}
</script>

<template>
  <div class="comparison">
    <p v-if="candidates.length === 0" class="muted">此 SEARCH 任務尚無候選。</p>
    <template v-else>
      <p class="muted">
        釘選至多 {{ MAX_PINNED }} 條候選並排比較（已選 {{ pinned.length }} 條）。凍結前只呈現擬合資訊，final_test
        一律顯示「尚未評估」。
      </p>
      <ul class="pin-list">
        <li v-for="row in candidates" :key="row.id" class="pin-row">
          <label>
            <input
              type="checkbox"
              :checked="pinned.includes(row.id)"
              :disabled="!pinned.includes(row.id) && isFull"
              @change="emit('toggle', row.id)"
            >
            <span class="rank">#{{ row.development_rank ?? '—' }}</span>
            <span class="source">{{ row.source }}</span>
            <span class="mono id">{{ row.id }}</span>
          </label>
          <RouterLink
            v-if="runId !== undefined && runId !== ''"
            class="pin-link"
            :to="{ name: 'candidate', params: { id: row.id }, query: { run: runId } }"
          >
            公式
          </RouterLink>
        </li>
      </ul>

      <p v-if="pinnedRows.length === 0" class="muted">請勾選候選以開始比較。</p>
      <p v-else-if="detailsLoading" class="muted">讀取公式與擬合內容中…</p>
      <div v-else class="scroll">
        <table class="matrix">
          <caption class="muted">候選比較（最多四條並排）</caption>
          <thead>
            <tr>
              <th scope="col">欄位</th>
              <th v-for="row in pinnedRows" :key="row.id" scope="col">
                #{{ row.development_rank ?? '—' }}<span class="mono block">{{ row.id }}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">來源</th>
              <td v-for="row in pinnedRows" :key="row.id">{{ row.source }}</td>
            </tr>
            <tr>
              <th scope="row">equation_version_id</th>
              <td v-for="row in pinnedRows" :key="row.id" class="mono">{{ row.equation_version_id }}</td>
            </tr>
            <tr>
              <th scope="row">公式</th>
              <td v-for="row in pinnedRows" :key="row.id" class="mono formula">{{ formulaFor(row) }}</td>
            </tr>
            <tr>
              <th scope="row">參數</th>
              <td v-for="row in pinnedRows" :key="row.id" class="mono">{{ parametersFor(row) }}</td>
            </tr>
            <tr>
              <th scope="row">參數有效位數</th>
              <td v-for="row in pinnedRows" :key="row.id">
                {{ precisionFor(row) ?? '載入中…' }}
              </td>
            </tr>
            <tr>
              <th scope="row">定義域</th>
              <td v-for="row in pinnedRows" :key="row.id" class="mono">{{ domainFor(row) }}</td>
            </tr>
            <tr>
              <th scope="row">模型複雜度</th>
              <td v-for="row in pinnedRows" :key="row.id">
                {{ complexityFor(row) ?? '載入中…' }}
              </td>
            </tr>
            <tr>
              <th scope="row">精度位元</th>
              <td v-for="row in pinnedRows" :key="row.id">{{ fitFor(row)?.precision_bits ?? '載入中…' }}</td>
            </tr>
            <tr>
              <th scope="row">驗證狀態</th>
              <td v-for="row in pinnedRows" :key="row.id">
                {{ statusLabels[row.validation_status] }}（{{ row.validation_status }}）
              </td>
            </tr>
            <tr>
              <th scope="row">final_test</th>
              <td v-for="row in pinnedRows" :key="row.id" class="muted">尚未評估／封存</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>

<style scoped>
.comparison {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.muted {
  color: var(--text-muted);
  font-size: 0.9rem;
}
.pin-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.pin-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.75rem;
}
.pin-link {
  font-size: 0.85rem;
  white-space: nowrap;
}
.pin-list label {
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
  font-size: 0.9rem;
}
.rank {
  color: var(--accent);
  min-width: 2.5rem;
}
.source {
  font-weight: 600;
}
.id {
  color: var(--text-muted);
  word-break: break-all;
}
.scroll {
  overflow-x: auto;
}
.matrix {
  border-collapse: collapse;
  width: 100%;
  min-width: 40rem;
}
.matrix caption {
  text-align: left;
  padding-bottom: 0.4rem;
}
.matrix th,
.matrix td {
  border: 1px solid var(--border);
  padding: 0.4rem 0.6rem;
  vertical-align: top;
  text-align: left;
  font-size: 0.9rem;
  overflow-wrap: anywhere;
}
.matrix thead th {
  background: var(--surface-muted);
}
.matrix tbody th {
  color: var(--text-muted);
  white-space: nowrap;
}
.block {
  display: block;
}
.formula {
  white-space: pre-wrap;
}
</style>

import { MAX_COMPARISON, type ValidationStatus } from '../api/candidates'
import type { DiscoverySearchRun } from './discoveries'
import type { VerificationSubmissionRow } from './verificationCenter'

export interface DiscoveryCandidatePreview {
  id: string
  source: string
  developmentRank: number | null
  validationStatus: ValidationStatus
}

export interface DiscoveriesHandoffSummary {
  runId: string
  researchId: string | null
  researchName: string
  versionId: string | null
  totalCandidates: number
  pinnedIds: string[]
  suggestedPinnedIds: string[]
  focusIds: string[]
  availableSlots: number
  statusCounts: Record<ValidationStatus, number>
  candidates: DiscoveryCandidatePreview[]
}

export interface VerificationVersionGroup {
  researchId: string
  researchName: string
  versionId: string
  submissionIds: string[]
  evaluatedCount: number
  pendingCount: number
  selectedSubmissionId: string | null
}

export interface VerificationHandoffSummary {
  totalSubmissions: number
  visibleSubmissions: number
  hiddenSubmissions: number
  selectedSubmissionId: string
  groups: VerificationVersionGroup[]
}

function uniqueOrdered(values: string[]): string[] {
  return [...new Set(values.filter((value) => value !== ''))]
}

export function buildDiscoveriesHandoffSummary(
  run: DiscoverySearchRun | null,
  pinned: string[],
  compareLimit = MAX_COMPARISON,
): DiscoveriesHandoffSummary | null {
  if (run === null) return null

  const allCandidateIds = run.candidates.map((candidate) => candidate.id)
  const available = new Set(allCandidateIds)
  const pinnedIds = uniqueOrdered(pinned).filter((id) => available.has(id))
  const suggestedPinnedIds = allCandidateIds.slice(0, compareLimit)
  const focusIds = pinnedIds.length === 0 ? allCandidateIds : pinnedIds
  const statusCounts: Record<ValidationStatus, number> = {
    NOT_RUN: 0,
    PENDING: 0,
    FINISHED: 0,
    INVALID: 0,
  }

  for (const candidate of run.candidates) statusCounts[candidate.validation_status] += 1

  return {
    runId: run.run.id,
    researchId: run.research?.id ?? null,
    researchName: run.research?.name ?? '未命名研究',
    versionId: run.version?.id ?? null,
    totalCandidates: run.candidates.length,
    pinnedIds,
    suggestedPinnedIds,
    focusIds,
    availableSlots: Math.max(0, compareLimit - pinnedIds.length),
    statusCounts,
    candidates: run.candidates.map((candidate) => ({
      id: candidate.id,
      source: candidate.source,
      developmentRank: candidate.development_rank,
      validationStatus: candidate.validation_status,
    })),
  }
}

export function groupVerificationRowsByVersion(
  rows: VerificationSubmissionRow[],
  selectedSubmissionId = '',
): VerificationVersionGroup[] {
  const groups = new Map<string, VerificationVersionGroup>()

  for (const row of rows) {
    const current = groups.get(row.version.id) ?? {
      researchId: row.version.research_id,
      researchName: row.research?.name ?? '未命名研究',
      versionId: row.version.id,
      submissionIds: [],
      evaluatedCount: 0,
      pendingCount: 0,
      selectedSubmissionId: null,
    }

    current.submissionIds.push(row.submissionId)
    if (row.finalEvaluation?.status === 'EVALUATED') current.evaluatedCount += 1
    else current.pendingCount += 1
    if (row.submissionId === selectedSubmissionId) current.selectedSubmissionId = row.submissionId

    groups.set(row.version.id, current)
  }

  return [...groups.values()].sort((left, right) => right.submissionIds.length - left.submissionIds.length)
}

export function buildVerificationHandoffSummary(
  allRows: VerificationSubmissionRow[],
  filteredIds: string[],
  selectedSubmissionId: string,
): VerificationHandoffSummary {
  const totalSubmissions = allRows.length
  const allowed = new Set(uniqueOrdered(filteredIds))
  const visibleRows = allowed.size === 0 ? allRows : allRows.filter((row) => allowed.has(row.submissionId))
  const groups = groupVerificationRowsByVersion(visibleRows, selectedSubmissionId)
  const resolvedSelectedSubmissionId =
    visibleRows.find((row) => row.submissionId === selectedSubmissionId)?.submissionId ?? visibleRows[0]?.submissionId ?? ''

  return {
    totalSubmissions,
    visibleSubmissions: visibleRows.length,
    hiddenSubmissions: Math.max(0, totalSubmissions - visibleRows.length),
    selectedSubmissionId: resolvedSelectedSubmissionId,
    groups,
  }
}

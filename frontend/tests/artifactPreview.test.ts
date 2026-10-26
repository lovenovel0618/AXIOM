import { describe, expect, it } from 'vitest'
import type { Artifact } from '../src/api/artifacts'
import { formatArtifactPreview, supportsArtifactPreview } from '../src/lib/artifactPreview'

const artifact = (media_type: string, access_class: Artifact['access_class'] = 'PROJECT'): Artifact => ({
  kind: 'Artifact',
  id: 'artifact-1',
  tenant_id: 'tenant-1',
  created_at: '2026-10-26T00:00:00Z',
  artifact_uri: 'minio://artifact-1',
  sha256: 'a'.repeat(64),
  status: 'AVAILABLE',
  owner_id: 'owner-1',
  size_bytes: 128,
  media_type,
  access_class,
})

describe('artifactPreview', () => {
  it('supports project json artifacts only', () => {
    expect(supportsArtifactPreview(artifact('application/json'))).toBe(true)
    expect(supportsArtifactPreview(artifact('application/problem+json'))).toBe(true)
    expect(supportsArtifactPreview(artifact('text/plain'))).toBe(false)
    expect(supportsArtifactPreview(artifact('application/json', 'SEALED_DETAIL'))).toBe(false)
  })

  it('formats a bounded pretty preview', () => {
    expect(formatArtifactPreview({ a: 1, b: [1, 2] })).toContain('"a": 1')
    expect(formatArtifactPreview({ text: 'x'.repeat(5000) }, 40)).toContain('...')
  })
})

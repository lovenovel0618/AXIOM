import type { Artifact } from '../api/artifacts'

export function supportsArtifactPreview(artifact: Artifact): boolean {
  if (artifact.access_class !== 'PROJECT') return false
  return artifact.media_type.includes('json') || artifact.media_type.endsWith('+json')
}

export function formatArtifactPreview(value: unknown, maxChars = 4000): string {
  const pretty = JSON.stringify(value, null, 2)
  if (pretty === undefined) return ''
  return pretty.length <= maxChars ? pretty : `${pretty.slice(0, maxChars)}\n...`
}

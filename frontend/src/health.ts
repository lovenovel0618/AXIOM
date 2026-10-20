export type HealthStatus = 'ready' | 'unavailable'
type Fetcher = (url: string, options: RequestInit) => Promise<Response>

export async function checkReadiness(fetcher: Fetcher = fetch): Promise<HealthStatus> {
  try {
    const response = await fetcher('/health/ready/', { signal: AbortSignal.timeout(5000), cache: 'no-store' })
    if (!response.ok) return 'unavailable'
    const body: unknown = await response.json()
    return typeof body === 'object' && body !== null && 'status' in body && body.status === 'ok'
      ? 'ready' : 'unavailable'
  } catch {
    return 'unavailable'
  }
}

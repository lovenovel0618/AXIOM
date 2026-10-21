/**
 * 同源 API 傳輸層：統一 CSRF、JSON 編解碼與穩定錯誤碼。
 * 後端回應一律視為不可信輸入，只在這裡解析成固定形狀。
 */
export type Fetcher = (input: string, init?: RequestInit) => Promise<Response>

const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])
const CSRF_COOKIE = 'axiom_csrf'

export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly retryable: boolean

  constructor(code: string, status: number, retryable: boolean) {
    super(code)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.retryable = retryable
  }
}

export function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null
  const prefix = `${name}=`
  for (const part of document.cookie.split('; ')) {
    if (part.startsWith(prefix)) return decodeURIComponent(part.slice(prefix.length))
  }
  return null
}

/** 後端 put_url 為絕對網址；前端必須轉回相對路徑，才能沿用同源 proxy 與 cookie。 */
export function toRelativePath(url: string, base = 'http://localhost'): string {
  const parsed = new URL(url, base)
  return `${parsed.pathname}${parsed.search}`
}

/** 冪等鍵必須不可預測；一律使用 Web Crypto，缺少時直接失敗而非退回弱隨機。 */
export function newKey(): string {
  return globalThis.crypto.randomUUID()
}

export interface RequestOptions {
  json?: unknown
  body?: BodyInit
  headers?: Record<string, string>
  csrf?: string
}

export interface ApiClient {
  request<T>(method: string, path: string, options?: RequestOptions): Promise<T>
  text(method: string, path: string, options?: RequestOptions): Promise<string>
  csrfToken(): Promise<string>
}

async function toApiError(response: Response): Promise<ApiError> {
  let code = 'INTERNAL_ERROR'
  let retryable = response.status === 503
  try {
    const body: unknown = await response.json()
    if (typeof body === 'object' && body !== null) {
      if ('code' in body && typeof body.code === 'string' && body.code !== '') code = body.code
      if ('retryable' in body && typeof body.retryable === 'boolean') retryable = body.retryable
    }
  } catch {
    // 非 JSON 錯誤頁（代理或框架層）仍以狀態碼呈現。
  }
  return new ApiError(code, response.status, retryable)
}

async function parseBody<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as unknown as T
  const text = await response.text()
  if (text === '') return undefined as unknown as T
  try {
    return JSON.parse(text) as T
  } catch {
    throw new ApiError('INVALID_RESPONSE', response.status, false)
  }
}

export function createApiClient(fetcher: Fetcher = fetch, cookieSource: (name: string) => string | null = readCookie): ApiClient {
  async function csrfToken(): Promise<string> {
    const existing = cookieSource(CSRF_COOKIE)
    if (existing !== null && existing !== '') return existing
    const seeded = await fetcher('/auth/login', { method: 'GET', credentials: 'same-origin' })
    if (!seeded.ok) throw await toApiError(seeded)
    const token = cookieSource(CSRF_COOKIE)
    if (token === null || token === '') throw new ApiError('CSRF_FAILED', 403, false)
    return token
  }

  async function send(method: string, path: string, options: RequestOptions): Promise<Response> {
    const upper = method.toUpperCase()
    const headers = new Headers(options.headers ?? {})
    headers.set('Accept', 'application/json')
    let body = options.body
    if (options.json !== undefined) {
      headers.set('Content-Type', 'application/json')
      body = JSON.stringify(options.json)
    }
    if (UNSAFE_METHODS.has(upper)) headers.set('X-CSRFToken', options.csrf ?? (await csrfToken()))
    const response = await fetcher(path, { method: upper, headers, body, credentials: 'same-origin' })
    if (!response.ok) throw await toApiError(response)
    return response
  }

  async function request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
    return parseBody<T>(await send(method, path, options))
  }

  /** SSE 等非 JSON 回應走這條路徑，錯誤仍統一轉成 ApiError。 */
  async function text(method: string, path: string, options: RequestOptions = {}): Promise<string> {
    return (await send(method, path, options)).text()
  }

  return { request, text, csrfToken }
}

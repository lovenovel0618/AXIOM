/** 同源 session 認證：登入表單為 form-urlencoded，登出必須帶 CSRF。 */
import { ApiError, type ApiClient } from './client'

export async function signIn(client: ApiClient, username: string, password: string): Promise<void> {
  await client.request<unknown>('POST', '/auth/login', {
    csrf: await client.csrfToken(),
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ username, password }),
  })
}

export async function signOut(client: ApiClient): Promise<void> {
  await client.request<unknown>('POST', '/auth/logout', { csrf: await client.csrfToken() })
}

/** 以後端最便宜的已授權端點探測 session；401／403 代表尚未登入。 */
export async function isSignedIn(client: ApiClient): Promise<boolean> {
  try {
    await client.request<unknown>('GET', '/api/v2/datasets?limit=1')
    return true
  } catch (error) {
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) return false
    throw error
  }
}

/** 單一前台 API 實例與工作階段狀態；畫面只讀 session，不直接持有 client。 */
import { computed, reactive } from 'vue'
import { isSignedIn, signIn, signOut } from '../api/auth'
import { createApiClient, type ApiClient } from '../api/client'

export const client: ApiClient = createApiClient()

export type SessionStatus = 'unknown' | 'signed-in' | 'signed-out'

const state = reactive<{ status: SessionStatus }>({ status: 'unknown' })

export const sessionStatus = computed<SessionStatus>(() => state.status)
export const isAuthenticated = computed<boolean>(() => state.status === 'signed-in')

export async function restoreSession(): Promise<void> {
  try {
    state.status = (await isSignedIn(client)) ? 'signed-in' : 'signed-out'
  } catch {
    state.status = 'signed-out'
  }
}

export async function logIn(username: string, password: string): Promise<void> {
  await signIn(client, username, password)
  state.status = 'signed-in'
}

export async function logOut(): Promise<void> {
  try {
    await signOut(client)
  } finally {
    state.status = 'signed-out'
  }
}

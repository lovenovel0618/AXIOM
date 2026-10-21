/** 內容雜湊：上傳前於瀏覽器計算 SHA-256，與後端固定版本的雜湊必須一致。 */
export async function sha256Hex(data: BufferSource): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', data)
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

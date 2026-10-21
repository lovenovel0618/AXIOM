/** 錯誤碼對應繁中說明；未知代碼仍保留原始碼以便診斷。 */
import { ApiError } from '../api/client'

const MESSAGES: Record<string, string> = {
  AUTH_REQUIRED: '請先登入。',
  FORBIDDEN: '目前身分沒有執行這個操作的權限。',
  NOT_FOUND: '找不到指定的資源。',
  INVALID_SCHEMA: '輸入內容不符合規格。',
  INVALID_JSON: '請求內容不是有效的 JSON。',
  INVALID_CURSOR: '分頁資料已失效，請重新載入。',
  INVALID_TRANSITION: '目前狀態不允許這個操作（可能已逾期或已完成）。',
  REVISION_CONFLICT: '任務狀態已被其他操作改變，請重新載入後再試。',
  PRECONDITION_REQUIRED: '缺少控制版本資訊，請重新載入後再試。',
  UNSUPPORTED_MEDIA_TYPE: '不支援的檔案格式，請使用 CSV、JSON 或 PARQUET。',
  UPLOAD_TOO_LARGE: '檔案超過大小上限（50 MiB）。',
  UPLOAD_OBJECT_CHANGED: '已上傳的內容與登記的雜湊不一致。',
  CHECKSUM_MISMATCH: '內容雜湊不符，請重新上傳。',
  IDEMPOTENCY_CONFLICT: '相同請求識別碼卻內容不同，請重新操作。',
  CSRF_FAILED: '工作階段驗證失敗，請重新登入。',
  RATE_LIMITED: '請求過於頻繁，請稍後再試。',
  DEPENDENCY_UNAVAILABLE: '後端服務暫時無法使用（匯入功能可能尚未啟用）。',
  ARTIFACT_UNAVAILABLE: '產物目前無法取得。',
  INTERNAL_ERROR: '伺服器發生未預期的錯誤。',
  INVALID_RESPONSE: '伺服器回應格式不正確。',
  NETWORK_ERROR: '無法連線到後端服務。',
}

export function describeError(error: unknown): string {
  if (error instanceof ApiError) return MESSAGES[error.code] ?? `操作失敗（${error.code}）。`
  return MESSAGES.NETWORK_ERROR ?? '操作失敗。'
}

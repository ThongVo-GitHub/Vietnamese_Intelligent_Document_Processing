import type {
  Alert, AlertListResponse, AlertSeverity, AlertStatus, AnalysisResult, Dossier,
  FileUploadResponse, ProcessingJob, ReconcileResponse, SearchParams, SearchResponse, Uuid,
} from './types'

const BASE_URL = '/api'

export class ApiError extends Error {
  status: number
  detail: unknown

  constructor(status: number, message: string, detail?: unknown) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

// Câu báo lỗi tiếng Việt theo bảng ở mục 4 của contract
const ERROR_MESSAGES: Record<number, string> = {
  400: 'Dữ liệu hoặc tên file không hợp lệ',
  404: 'Không tìm thấy dữ liệu',
  413: 'File vượt quá giới hạn 10 MB',
  415: 'Loại file không được hỗ trợ (chỉ nhận PDF, PNG, JPEG, XML)',
  422: 'Dữ liệu gửi lên không đúng định dạng',
  500: 'Lỗi máy chủ, vui lòng thử lại sau',
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response
  try {
    res = await fetch(BASE_URL + path, init)
  } catch {
    // fetch chỉ ném lỗi khi không kết nối được (backend tắt, mất mạng)
    throw new ApiError(0, 'Không kết nối được máy chủ')
  }

  const body = await res.json().catch(() => null)

  if (!res.ok) {
    const detail = body?.detail
    throw new ApiError(res.status, ERROR_MESSAGES[res.status] ?? `Lỗi ${res.status}`, detail)
  }

  return body as T
}

function jsonBody(method: string, data: unknown): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }
}

function toQuery(params: object): string {
  const entries = Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .map(([key, value]) => [key, String(value)])
  return entries.length > 0 ? '?' + new URLSearchParams(entries) : ''
}

export const api = {
  // 3.1 Tạo hồ sơ
  createDossier: (name: string) =>
    request<Dossier>('/dossiers', jsonBody('POST', { name })),

  // 3.2 Upload file: multipart/form-data, field bắt buộc tên "file"
  uploadFile: (dossierId: Uuid, file: File) => {
    const form = new FormData()
    form.append('file', file)
    // KHÔNG tự đặt Content-Type: trình duyệt tự thêm kèm "boundary"
    return request<FileUploadResponse>(`/dossiers/${dossierId}/files`, {
      method: 'POST',
      body: form,
    })
  },

  // 3.3 Xem trạng thái job
  getJob: (jobId: Uuid) => request<ProcessingJob>(`/jobs/${jobId}`),

  // 3.4 Lấy kết quả phân tích (chỉ gọi khi job "succeeded", chưa có thì 404)
  getJobResult: (jobId: Uuid) => request<AnalysisResult>(`/jobs/${jobId}/result`),

  // 3.5 Chạy đối chiếu
  reconcile: (dossierId: Uuid) =>
    request<ReconcileResponse>(`/dossiers/${dossierId}/reconcile`, { method: 'POST' }),

  // 3.6 Danh sách cảnh báo, có thể lọc theo status, severity
  listAlerts: (dossierId: Uuid, filter: { status?: AlertStatus; severity?: AlertSeverity } = {}) =>
    request<AlertListResponse>(`/dossiers/${dossierId}/alerts${toQuery(filter)}`),

  // 3.7 Đổi trạng thái cảnh báo (backend trả về alert sau khi cập nhật)
  updateAlert: (dossierId: Uuid, alertId: Uuid, status: AlertStatus) =>
    request<Alert>(`/dossiers/${dossierId}/alerts/${alertId}`, jsonBody('PATCH', { status })),

  // 3.8 Tìm kiếm trong một hồ sơ
  search: (dossierId: Uuid, params: SearchParams = {}) =>
    request<SearchResponse>(`/dossiers/${dossierId}/search${toQuery(params)}`),
}
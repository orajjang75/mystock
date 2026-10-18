import axios, { AxiosError } from 'axios'

// Same origin: the dev server proxies /api to the backend, and production serves both together.
export const http = axios.create({ baseURL: '', withCredentials: true })

let unauthorizedHandler: (() => void) | null = null

/** Called when a request that needs a login comes back 401 (the session ended). */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler
}

http.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (isUnauthorized(error) && !isAuthRequest(error)) unauthorizedHandler?.()
    return Promise.reject(error)
  },
)

export function isUnauthorized(error: unknown): boolean {
  return error instanceof AxiosError && error.response?.status === 401
}

function isAuthRequest(error: unknown): boolean {
  return error instanceof AxiosError && (error.config?.url ?? '').startsWith('/api/auth/')
}

/** The ``detail`` message the API sent with an error, or a fallback. */
export function errorMessage(error: unknown, fallback = '요청을 처리하지 못했습니다'): string {
  if (error instanceof AxiosError) {
    const detail: unknown = error.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail.length > 0) {
      const first: unknown = detail[0]
      if (typeof first === 'object' && first !== null && 'msg' in first) return String(first.msg)
    }
    if (!error.response) return '서버에 연결할 수 없습니다'
  }
  return fallback
}

import axios from 'axios'

export const http = axios.create({ baseURL: '/api/v1', timeout: 30_000 })
http.interceptors.response.use((response) => response, (error: unknown) => {
  if (axios.isAxiosError(error) && !axios.isCancel(error)) {
    const payload = error.response?.data as { message?: string; detail?: unknown } | undefined
    const message = payload?.message || (typeof payload?.detail === 'string' ? payload.detail : undefined)
    if (message) error.message = message
  }
  return Promise.reject(error)
})

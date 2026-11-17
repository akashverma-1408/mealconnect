/**
 * Axios instance shared by the whole app.
 *
 * Token handling
 * - The short-lived ACCESS token lives only in memory (a module variable), so it is
 *   gone when the tab closes and is never written to disk.
 * - The REFRESH token is kept in localStorage so a page reload keeps you logged in.
 * - When a request fails with 401, we refresh once and retry the request.
 *
 * Refresh tokens are single-use on the server (rotation + reuse detection). If two
 * requests refreshed at the same time with the same token, the server would treat the
 * second as a stolen token and log the user out everywhere. So all callers share ONE
 * in-flight refresh promise ("single-flight").
 */
import axios from 'axios'

const REFRESH_KEY = 'mc_refresh_token'
export const API_BASE = import.meta.env.VITE_API_URL || '/api/v1'

let accessToken = null
let refreshPromise = null
let onSessionExpired = () => {}

export const tokenStore = {
  getAccess: () => accessToken,
  getRefresh: () => {
    try {
      return localStorage.getItem(REFRESH_KEY)
    } catch {
      return null
    }
  },
  set({ access_token, refresh_token }) {
    accessToken = access_token
    try {
      localStorage.setItem(REFRESH_KEY, refresh_token)
    } catch {
      /* private mode: stay logged in for this tab only */
    }
  },
  clear() {
    accessToken = null
    try {
      localStorage.removeItem(REFRESH_KEY)
    } catch {
      /* ignore */
    }
  },
}

/** AuthContext registers what to do when the session cannot be refreshed. */
export function setSessionExpiredHandler(fn) {
  onSessionExpired = fn
}

export const api = axios.create({ baseURL: API_BASE, timeout: 15000 })

api.interceptors.request.use((config) => {
  if (accessToken) config.headers.Authorization = `Bearer ${accessToken}`
  return config
})

/** Exchange the stored refresh token for a new pair. Concurrent callers share one call. */
export function refreshTokens() {
  if (!refreshPromise) {
    const refresh_token = tokenStore.getRefresh()
    refreshPromise = (
      refresh_token
        ? axios.post(`${API_BASE}/auth/refresh`, { refresh_token }).then((res) => {
            tokenStore.set(res.data)
            return res.data
          })
        : Promise.reject(new Error('No refresh token'))
    ).finally(() => {
      refreshPromise = null
    })
  }
  return refreshPromise
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config
    const status = error.response?.status
    const isAuthCall = original?.url?.startsWith('/auth/')
    if (status === 401 && original && !original._retried && !isAuthCall && tokenStore.getRefresh()) {
      original._retried = true
      try {
        await refreshTokens()
        return api(original) // retry once with the new access token
      } catch {
        tokenStore.clear()
        onSessionExpired()
      }
    }
    return Promise.reject(error)
  },
)

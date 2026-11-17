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

const LOCK_NAME = 'mealconnect-token-refresh'

/**
 * Exchange the stored refresh token for a new pair.
 *
 * Two layers of protection against sending the same (single-use) token twice:
 * 1. Inside this tab, concurrent callers share one promise.
 * 2. Across tabs (and duplicate module copies after a hot reload), the Web Locks API
 *    runs one refresh at a time, and the token is read INSIDE the lock — so if another
 *    tab just rotated it, we use the new one instead of replaying the old one.
 */
export function refreshTokens() {
  if (!refreshPromise) {
    const run = () => {
      const refresh_token = tokenStore.getRefresh()
      if (!refresh_token) return Promise.reject(new Error('No refresh token'))
      return axios.post(`${API_BASE}/auth/refresh`, { refresh_token }).then((res) => {
        tokenStore.set(res.data)
        return res.data
      })
    }
    const locks = typeof navigator !== 'undefined' ? navigator.locks : undefined
    refreshPromise = (locks?.request ? locks.request(LOCK_NAME, run) : run()).finally(() => {
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
    if (status === 403 && error.response?.data?.error?.code === 'ACCOUNT_SUSPENDED' && !isAuthCall) {
      tokenStore.clear()
      onSessionExpired('Your account has been suspended. Please contact support.')
      return Promise.reject(error)
    }
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

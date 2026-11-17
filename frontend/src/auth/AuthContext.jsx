/**
 * Global authentication state (who is logged in), shared through React Context.
 *
 * On first load we try to restore the session from the stored refresh token.
 * The bootstrap promise is module-level so React StrictMode's double-invoked effects
 * in development cannot start two refreshes (which the server would flag as token reuse).
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { refreshTokens, setSessionExpiredHandler, tokenStore } from '../api/client'
import { authApi } from '../api/endpoints'

const AuthContext = createContext(null)

let bootstrapPromise = null
function bootstrapSession() {
  if (!bootstrapPromise) {
    bootstrapPromise = tokenStore.getRefresh()
      ? refreshTokens()
          .then(() => authApi.me())
          .catch(() => {
            tokenStore.clear()
            return null
          })
      : Promise.resolve(null)
  }
  return bootstrapPromise
}

/** Test helper: forget the cached bootstrap between tests. */
export function resetAuthBootstrap() {
  bootstrapPromise = null
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const queryClient = useQueryClient()

  useEffect(() => {
    let active = true
    bootstrapSession().then((me) => {
      if (active) {
        setUser(me)
        setLoading(false)
      }
    })
    return () => {
      active = false
    }
  }, [])

  const [notice, setNotice] = useState(null) // why the session ended, if not by the user

  const clearSession = useCallback(
    (reason) => {
      tokenStore.clear()
      setUser(null)
      setNotice(typeof reason === 'string' ? reason : null)
      queryClient.clear() // never show the previous user's cached data
    },
    [queryClient],
  )

  useEffect(() => {
    setSessionExpiredHandler(clearSession)
  }, [clearSession])

  const login = useCallback(async (email, password) => {
    setNotice(null)
    const res = await authApi.login({ email, password })
    tokenStore.set(res)
    setUser(res.user)
    return res.user
  }, [])

  const register = useCallback(
    async (body) => {
      await authApi.register(body)
      return login(body.email, body.password)
    },
    [login],
  )

  const logout = useCallback(async () => {
    const refresh = tokenStore.getRefresh()
    try {
      if (refresh) await authApi.logout(refresh)
    } catch {
      /* already invalid on the server: nothing else to do */
    } finally {
      clearSession()
    }
  }, [clearSession])

  const value = useMemo(
    () => ({ user, setUser, loading, login, register, logout, notice }),
    [user, loading, login, register, logout, notice],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}

import axios from 'axios'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, refreshTokens, setSessionExpiredHandler, tokenStore } from './client'

afterEach(() => vi.restoreAllMocks())

describe('refreshTokens', () => {
  it('shares ONE request between concurrent callers (refresh tokens are single-use)', async () => {
    tokenStore.set({ access_token: 'old-access', refresh_token: 'refresh-1' })
    const post = vi.spyOn(axios, 'post').mockResolvedValue({
      data: { access_token: 'new-access', refresh_token: 'refresh-2' },
    })

    const results = await Promise.all([refreshTokens(), refreshTokens(), refreshTokens()])

    expect(post).toHaveBeenCalledTimes(1)
    expect(post).toHaveBeenCalledWith('/api/v1/auth/refresh', { refresh_token: 'refresh-1' })
    expect(results.every((r) => r.access_token === 'new-access')).toBe(true)
    expect(tokenStore.getAccess()).toBe('new-access')
    expect(tokenStore.getRefresh()).toBe('refresh-2')
  })

  it('rejects without calling the API when there is no refresh token', async () => {
    tokenStore.clear()
    const post = vi.spyOn(axios, 'post')
    await expect(refreshTokens()).rejects.toThrow('No refresh token')
    expect(post).not.toHaveBeenCalled()
  })
})

describe('refreshTokens across tabs', () => {
  it('reads the token inside a Web Lock so a token rotated by another tab is not replayed', async () => {
    tokenStore.set({ access_token: 'a', refresh_token: 'stale-token' })
    // Simulate another tab rotating the token while we wait for the lock.
    const locks = {
      request: vi.fn(async (name, fn) => {
        localStorage.setItem('mc_refresh_token', 'rotated-by-other-tab')
        return fn()
      }),
    }
    vi.stubGlobal('navigator', { ...navigator, locks })
    const post = vi.spyOn(axios, 'post').mockResolvedValue({
      data: { access_token: 'x', refresh_token: 'newest' },
    })
    await refreshTokens()
    expect(locks.request).toHaveBeenCalledWith('mealconnect-token-refresh', expect.any(Function))
    expect(post).toHaveBeenCalledWith('/api/v1/auth/refresh', { refresh_token: 'rotated-by-other-tab' })
    vi.unstubAllGlobals()
  })
})

describe('response interceptor', () => {
  it('ends the session with a message when the account is suspended mid-session', async () => {
    tokenStore.set({ access_token: 'a', refresh_token: 'r' })
    const handler = vi.fn()
    setSessionExpiredHandler(handler)
    const suspended = Object.assign(new Error('403'), {
      config: { url: '/orders' },
      response: { status: 403, data: { error: { code: 'ACCOUNT_SUSPENDED', message: 'suspended' } } },
    })
    const original = api.defaults.adapter
    api.defaults.adapter = () => Promise.reject(suspended)
    try {
      await expect(api.get('/orders')).rejects.toBe(suspended)
    } finally {
      api.defaults.adapter = original
    }
    expect(handler).toHaveBeenCalledWith(expect.stringMatching(/suspended/))
    expect(tokenStore.getRefresh()).toBeNull()
  })
})

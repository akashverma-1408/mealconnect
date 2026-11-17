import axios from 'axios'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { refreshTokens, tokenStore } from './client'

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

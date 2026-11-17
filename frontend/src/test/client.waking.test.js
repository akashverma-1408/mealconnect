import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, serverWaking } from '../api/client'

describe('server waking indicator', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('turns on for a slow request and off when it finishes', async () => {
    let finish
    api.defaults.adapter = (config) =>
      new Promise((resolve) => {
        finish = () => resolve({ data: {}, status: 200, statusText: 'OK', headers: {}, config })
      })
    const pending = api.get('/health')
    expect(serverWaking.getSnapshot()).toBe(false)
    await vi.advanceTimersByTimeAsync(4100)
    expect(serverWaking.getSnapshot()).toBe(true)
    finish()
    await pending
    expect(serverWaking.getSnapshot()).toBe(false)
  })

  it('stays off for a fast request', async () => {
    api.defaults.adapter = (config) =>
      Promise.resolve({ data: {}, status: 200, statusText: 'OK', headers: {}, config })
    await api.get('/health')
    await vi.advanceTimersByTimeAsync(5000)
    expect(serverWaking.getSnapshot()).toBe(false)
  })

  it('turns off when the request fails', async () => {
    api.defaults.adapter = (config) =>
      new Promise((_, reject) => setTimeout(() => reject(Object.assign(new Error('x'), { config })), 6000))
    const pending = api.get('/health').catch(() => 'failed')
    await vi.advanceTimersByTimeAsync(4100)
    expect(serverWaking.getSnapshot()).toBe(true)
    await vi.advanceTimersByTimeAsync(2500)
    expect(await pending).toBe('failed')
    expect(serverWaking.getSnapshot()).toBe(false)
  })
})

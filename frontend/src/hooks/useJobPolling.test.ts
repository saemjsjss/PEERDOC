import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import { json, makeJob } from '../test/jobs'
import { GIVE_UP_MS, useJobPolling } from './useJobPolling'

const tick = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms))
const jobCalls = (fetch: Mock) => fetch.mock.calls.filter(([url]) => String(url).startsWith('/jobs/')).length

function setup(fetch: Mock, jobId: string | null = 'j1') {
  vi.stubGlobal('fetch', fetch)
  const onGone = vi.fn()
  const hook = renderHook(({ id }) => useJobPolling(id, onGone), { initialProps: { id: jobId } })
  return { ...hook, onGone }
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('useJobPolling', () => {
  it.each(['done', 'failed'] as const)('polls every 2 s and stops once the job is %s', async (status) => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(json(makeJob()))
      .mockResolvedValueOnce(json(makeJob({ status, stage: 'finished' })))
    const { result } = setup(fetch)
    await tick(0)
    expect(result.current.job?.status).toBe('running')
    await tick(2000)
    expect(result.current.job?.status).toBe(status)
    await tick(60_000)
    expect(jobCalls(fetch)).toBe(2)
  })

  it('backs off 4, 8, 16, then 30 s while the server is unreachable', async () => {
    const fetch = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    const { result } = setup(fetch)
    await tick(0)
    expect(jobCalls(fetch)).toBe(1)
    expect(result.current.reconnecting).toBe(true)
    await tick(3999)
    expect(jobCalls(fetch)).toBe(1)
    await tick(1) // 4 s
    expect(jobCalls(fetch)).toBe(2)
    await tick(8000)
    expect(jobCalls(fetch)).toBe(3)
    await tick(16000)
    expect(jobCalls(fetch)).toBe(4)
    await tick(29999)
    expect(jobCalls(fetch)).toBe(4)
    await tick(1) // capped at 30 s
    expect(jobCalls(fetch)).toBe(5)
  })

  it('gives up after 5 minutes of server errors, and keeps waiting on request', async () => {
    const fetch = vi.fn().mockImplementation(async () => json({ detail: 'boom' }, 503))
    const { result } = setup(fetch)
    await tick(GIVE_UP_MS + 30_000)
    expect(result.current.stalled).toMatch(/error \(503\)/)
    expect(result.current.reconnecting).toBe(false)
    const calls = jobCalls(fetch)
    await tick(120_000)
    expect(jobCalls(fetch)).toBe(calls) // stopped

    fetch.mockImplementation(async () => json(makeJob()))
    act(() => result.current.keepWaiting())
    await tick(0)
    expect(jobCalls(fetch)).toBe(calls + 1)
    expect(result.current.stalled).toBeNull()
    expect(result.current.job?.status).toBe('running')
  })

  it('says the server could not be reached when it gives up on network errors', async () => {
    const fetch = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    const { result } = setup(fetch)
    await tick(GIVE_UP_MS + 30_000)
    expect(result.current.stalled).toMatch(/could not be reached/)
  })

  it('calls onGone on 404 and stops', async () => {
    const fetch = vi.fn().mockImplementation(async () => json({ detail: 'not found' }, 404))
    const { onGone } = setup(fetch)
    await tick(10_000)
    expect(onGone).toHaveBeenCalledOnce()
    expect(onGone.mock.calls[0]?.[0]).toMatch(/no longer on the server/)
    expect(jobCalls(fetch)).toBe(1)
  })

  it('says the server restarted when its id changed', async () => {
    const fetch: Mock = vi.fn(async (url: string) => {
      if (url === '/health') return json({ models_loaded: true, server_id: 'new' })
      return jobCalls(fetch) === 1 ? json(makeJob({ server_id: 'old' })) : json({ detail: 'not found' }, 404)
    })
    const { onGone } = setup(fetch)
    await tick(2000)
    expect(onGone).toHaveBeenCalledWith('The server restarted; please upload again.')
  })

  it('ignores a response that arrives after unmount', async () => {
    let answer: (r: Response) => void = () => {}
    let signal: AbortSignal | null | undefined
    const fetch = vi.fn((_url: string, init: RequestInit) => {
      signal = init.signal
      return new Promise<Response>((resolve) => (answer = resolve))
    })
    const { unmount, onGone } = setup(fetch)
    unmount()
    expect(signal?.aborted).toBe(true)
    answer(json({ detail: 'not found' }, 404))
    await tick(10_000)
    expect(onGone).not.toHaveBeenCalled()
    expect(jobCalls(fetch)).toBe(1)
  })

  it('drops the old job when the id changes', async () => {
    const fetch = vi.fn(async (url: string) => {
      if (url === '/jobs/j1') return json(makeJob())
      return new Promise<Response>(() => {}) // j2 has not answered yet
    })
    const { result, rerender } = setup(fetch)
    await tick(0)
    expect(result.current.job?.job_id).toBe('j1')
    rerender({ id: 'j2' })
    expect(result.current.job).toBeNull()
    await tick(2000)
    expect(result.current.job).toBeNull()
  })
})

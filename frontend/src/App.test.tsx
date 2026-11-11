import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import App from './App'
import { submitJob, type Verdict } from './api'
import fixture from './test/fixtures/verdict-flag.json'
import { json, makeJob } from './test/jobs'

vi.mock('./api', async (importOriginal) => ({ ...(await importOriginal<typeof import('./api')>()), submitJob: vi.fn() }))

const verdict = fixture as unknown as Verdict
const tick = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms))

/** Stub the server: /health is ready, GET /jobs/* answers from `jobs` in turn, DELETE as given. */
function server(jobs: Response[], del: () => Response | Promise<Response> = () => new Response(null, { status: 204 })): Mock {
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/health') return json({ models_loaded: true })
    if (init?.method === 'DELETE') return del()
    return jobs.length > 1 ? jobs.shift()! : jobs[0]!.clone()
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

async function upload() {
  vi.mocked(submitJob).mockResolvedValue(makeJob({ status: 'queued', stage: 'waiting' }))
  const input = document.querySelector<HTMLInputElement>('input[type=file]')!
  fireEvent.change(input, { target: { files: [new File(['%PDF'], 'a.pdf', { type: 'application/pdf' })] } })
  fireEvent.click(screen.getByRole('button', { name: 'Verify documents' }))
  await tick(0)
}

beforeEach(() => {
  vi.useFakeTimers()
  Element.prototype.scrollIntoView = vi.fn()
  sessionStorage.clear()
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('App', () => {
  it('goes from upload to progress to the results', async () => {
    server([
      json(makeJob({ message: 'Reading page 2 of 5' })),
      json(makeJob({ status: 'done', stage: 'finished', progress: 1, result: verdict })),
    ])
    render(<App />)
    expect(screen.getByRole('heading', { level: 1 })).toHaveFocus()
    await upload()
    expect(sessionStorage.getItem('hklv.jobId')).toBe('j1')
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Reading page 2 of 5')
    expect(screen.getByRole('heading', { level: 1 })).toHaveFocus()
    await tick(2000)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('FLAG')
  })

  it('explains when a queued job can no longer be cancelled (409)', async () => {
    const fetch = server([json(makeJob({ status: 'queued', stage: 'waiting', queue_position: 1 }))], () =>
      json({ detail: 'already running' }, 409),
    )
    render(<App />)
    await upload()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await tick(0)
    expect(screen.getByRole('alert')).toHaveTextContent(/can no longer be stopped/)
    const del = fetch.mock.calls.find(([, init]) => init?.method === 'DELETE')
    expect(del?.[1]?.headers).toMatchObject({ 'X-HKLV': '1' })
  })

  it('resumes tracking the job remembered for this tab', async () => {
    sessionStorage.setItem('hklv.jobId', 'j9')
    const fetch = server([json(makeJob({ job_id: 'j9', message: 'Reading page 4 of 5' }))])
    render(<App />)
    await tick(0)
    expect(fetch).toHaveBeenCalledWith('/jobs/j9', expect.anything())
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Reading page 4 of 5')
  })

  it('treats a finished job without a verdict as failed', async () => {
    sessionStorage.setItem('hklv.jobId', 'j1')
    server([json(makeJob({ status: 'done', stage: 'finished', result: null }))])
    render(<App />)
    await tick(0)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('The check could not be completed')
  })

  it('"Check another case" returns at once, without waiting for the delete', async () => {
    sessionStorage.setItem('hklv.jobId', 'j1')
    const fetch = server(
      [json(makeJob({ status: 'done', stage: 'finished', result: verdict }))],
      () => new Promise<Response>(() => {}), // the server never answers the delete
    )
    render(<App />)
    await tick(0)
    fireEvent.click(screen.getByRole('button', { name: /Check another case/ }))
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent("Check a student's documents")
    expect(sessionStorage.getItem('hklv.jobId')).toBeNull()
    const del = fetch.mock.calls.find(([, init]) => init?.method === 'DELETE')
    expect(del?.[1]?.signal).toBeInstanceOf(AbortSignal)
  })
})

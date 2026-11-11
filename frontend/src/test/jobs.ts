import type { Job } from '../api'

/** A job as GET /jobs/{id} returns it; override what the test cares about. */
export function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    job_id: 'j1',
    status: 'running',
    stage: 'reading',
    message: 'Reading the pages',
    case_id: 'case-1',
    pages_done: 1,
    pages_total: 5,
    progress: 0.2,
    eta_seconds: 60,
    queue_position: null,
    created_at: '2026-11-12T10:00:00Z',
    started_at: '2026-11-12T10:00:01Z',
    finished_at: null,
    files: { accepted: ['a.pdf'], ignored: [], ignored_more: 0 },
    result: null,
    error: null,
    ...overrides,
  }
}

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

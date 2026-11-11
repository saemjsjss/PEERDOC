// Client for the HKLV API (see docs/api.md). Types mirror the server's JSON.

export type Outcome = 'PASS' | 'FLAG' | 'FAIL'
export type JobStatus = 'queued' | 'running' | 'done' | 'failed'
export type Stage = 'waiting' | 'reading' | 'checking' | 'finished'

export interface Evidence {
  doc_id: string
  field: string
  value: string | null
  page: number | null
}

export interface RuleResult {
  rule_id: string
  outcome: Outcome
  reason: string
  evidence: Evidence[]
}

export interface FileReport {
  accepted: string[]
  ignored: { name: string; reason: string }[]
  ignored_more: number
}

export interface PageReport {
  page_no: number
  source_file: string
  file_page: number
  kind: string
  reason: string
  doc_id: string | null
}

export interface OnlineResult {
  doc_id: string
  kind: string
  status: string | null
  detail: string
}

export interface Verdict {
  case_id: string
  evaluation_date: string
  outcome: Outcome
  summary: string
  counts: { passed: number; flagged: number; failed: number }
  failures: RuleResult[]
  flags: RuleResult[]
  results: RuleResult[]
  documents: Record<string, unknown>[]
  pages: PageReport[]
  online: OnlineResult[]
  files: FileReport
  timings: Record<string, number>
}

export interface Job {
  job_id: string
  status: JobStatus
  stage: Stage
  message: string
  case_id: string
  pages_done: number
  pages_total: number
  progress: number
  eta_seconds: number | null
  queue_position: number | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  files: FileReport
  result: Verdict | null
  error: string | null
}

export interface SubmitOptions {
  caseId?: string
  evaluationDate?: string // YYYY-MM-DD
  online: boolean
}

export class ApiError extends Error {
  readonly status: number
  readonly ignored: FileReport['ignored']

  constructor(status: number, message: string, ignored: FileReport['ignored'] = []) {
    super(message)
    this.status = status
    this.ignored = ignored
  }
}

function errorFrom(status: number, body: unknown): ApiError {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return new ApiError(status, detail)
  if (detail && typeof detail === 'object') {
    const d = detail as { message?: string; ignored?: FileReport['ignored'] }
    if (d.message) return new ApiError(status, d.message, d.ignored ?? [])
    if (Array.isArray(detail)) return new ApiError(status, 'Some of the entered values are not valid.')
  }
  if (status === 0) return new ApiError(0, 'The verification server could not be reached. Is it running?')
  return new ApiError(status, `The server answered with an error (${status}).`)
}

/** Upload the files and start a job. Reports upload progress (0..1); XHR is used because
 * fetch cannot report upload progress. */
export function submitJob(
  files: File[],
  options: SubmitOptions,
  onUploadProgress: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<Job> {
  const form = new FormData()
  for (const file of files) form.append('files', file, file.name)
  if (options.caseId?.trim()) form.append('case_id', options.caseId.trim())
  if (options.evaluationDate) form.append('evaluation_date', options.evaluationDate)
  form.append('online', options.online ? 'true' : 'false')

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/jobs')
    xhr.responseType = 'json'
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onUploadProgress(e.loaded / e.total)
    }
    xhr.onload = () => {
      if (xhr.status === 202 || xhr.status === 200) resolve(xhr.response as Job)
      else reject(errorFrom(xhr.status, xhr.response))
    }
    xhr.onerror = () => reject(errorFrom(0, null))
    xhr.onabort = () => reject(new DOMException('Upload cancelled', 'AbortError'))
    signal?.addEventListener('abort', () => xhr.abort(), { once: true })
    xhr.send(form)
  })
}

export async function getJob(jobId: string, signal?: AbortSignal): Promise<Job> {
  let response: Response
  try {
    response = await fetch(`/jobs/${encodeURIComponent(jobId)}`, { signal, cache: 'no-store' })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw errorFrom(0, null)
  }
  const body = await response.json().catch(() => null)
  if (!response.ok) throw errorFrom(response.status, body)
  return body as Job
}

/** Cancel a waiting job, or forget a finished one (the server keeps verdicts for an hour). */
export async function deleteJob(jobId: string): Promise<void> {
  const response = await fetch(`/jobs/${encodeURIComponent(jobId)}`, { method: 'DELETE' })
  if (!response.ok && response.status !== 404) {
    throw errorFrom(response.status, await response.json().catch(() => null))
  }
}

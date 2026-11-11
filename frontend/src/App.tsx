import { useCallback, useEffect, useRef, useState } from 'react'

import { API_HEADERS, ApiError, deleteJob, submitJob, type FileReport, type SubmitOptions } from './api'
import { ProgressScreen } from './components/ProgressScreen'
import { UploadScreen } from './components/UploadScreen'
import { EMPTY_DRAFT, type Draft } from './lib/draft'
import { ResultsScreen } from './components/ResultsScreen'
import { useJobPolling } from './hooks/useJobPolling'

// Only the job id is remembered (so a page refresh during the ~8-minute run resumes
// tracking). The verdict itself, which holds personal data, is never stored in the browser.
const JOB_KEY = 'hklv.jobId'
const STARTED_KEY = 'hklv.startedAt'

function remembered(key: string): string | null {
  try {
    return sessionStorage.getItem(key)
  } catch {
    return null
  }
}

function remember(key: string, value: string | null) {
  try {
    if (value === null) sessionStorage.removeItem(key)
    else sessionStorage.setItem(key, value)
  } catch {
    // storage unavailable (private mode): tracking just won't survive a refresh
  }
}

function useServerStatus() {
  const [status, setStatus] = useState<'checking' | 'ready' | 'loading' | 'offline'>('checking')
  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>
    const check = async () => {
      try {
        const r = await fetch('/health', { cache: 'no-store', headers: API_HEADERS })
        const body = (await r.json()) as { models_loaded?: boolean }
        if (!cancelled) setStatus(r.ok && body.models_loaded ? 'ready' : 'loading')
      } catch {
        if (!cancelled) setStatus('offline')
      }
      if (!cancelled) timer = setTimeout(check, 15000)
    }
    check()
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [])
  return status
}

export default function App() {
  const [jobId, setJobId] = useState<string | null>(() => remembered(JOB_KEY))
  const [startedAt, setStartedAt] = useState<number>(() => Number(remembered(STARTED_KEY)) || Date.now())
  const [uploadProgress, setUploadProgress] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [ignored, setIgnored] = useState<FileReport['ignored']>([])
  const [cancelling, setCancelling] = useState(false)
  const [cancelError, setCancelError] = useState<string | null>(null)
  const failedHeading = useRef<HTMLHeadingElement>(null)
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT)
  const uploadAbort = useRef<AbortController | null>(null)
  const server = useServerStatus()

  const reset = useCallback((message: string | null = null) => {
    setJobId(null)
    setUploadProgress(null)
    setCancelling(false)
    setCancelError(null)
    setError(message)
    remember(JOB_KEY, null)
    remember(STARTED_KEY, null)
  }, [])
  const { job, reconnecting, stalled, keepWaiting } = useJobPolling(jobId, reset)

  async function start(files: File[], options: SubmitOptions) {
    setError(null)
    setIgnored([])
    const t0 = Date.now()
    setStartedAt(t0)
    setUploadProgress(0)
    const controller = new AbortController()
    uploadAbort.current = controller
    try {
      const created = await submitJob(files, options, setUploadProgress, controller.signal)
      remember(JOB_KEY, created.job_id)
      remember(STARTED_KEY, String(t0))
      setJobId(created.job_id)
      setUploadProgress(null)
    } catch (e) {
      setUploadProgress(null)
      if ((e as Error).name === 'AbortError') return
      setError((e as Error).message)
      if (e instanceof ApiError) setIgnored(e.ignored)
    } finally {
      uploadAbort.current = null
    }
  }

  async function cancel() {
    if (uploadProgress !== null) {
      uploadAbort.current?.abort()
      return
    }
    if (!jobId) return
    setCancelling(true)
    setCancelError(null)
    try {
      await deleteJob(jobId)
      reset()
    } catch (e) {
      setCancelling(false)
      setCancelError(
        e instanceof ApiError && e.status === 409
          ? 'The pages had just started being read, so this check can no longer be stopped. The result will appear here.'
          : (e as Error).message,
      )
    }
  }

  function newCase() {
    // Forget the verdict on the server too: it holds the student's personal data. The UI
    // doesn't wait for that; a slow or stopped server just lets the delete time out.
    if (jobId) deleteJob(jobId, AbortSignal.timeout(5000)).catch(() => undefined)
    setDraft(EMPTY_DRAFT)
    reset()
  }

  // A file dropped outside the drop zone must not make the browser open it and leave the app
  // (mid-upload that would also abandon the upload).
  useEffect(() => {
    const block = (e: DragEvent) => e.preventDefault()
    window.addEventListener('dragover', block)
    window.addEventListener('drop', block)
    return () => {
      window.removeEventListener('dragover', block)
      window.removeEventListener('drop', block)
    }
  }, [])

  // A finished job without a verdict can't be shown; treat it as failed.
  const failed = job?.status === 'failed' || (job?.status === 'done' && !job.result)
  useEffect(() => {
    if (failed) failedHeading.current?.focus()
  }, [failed])

  let screen
  if (job?.status === 'done' && job.result) {
    screen = <ResultsScreen verdict={job.result} onNewCase={newCase} />
  } else if (job && failed) {
    screen = (
      <section className="mx-auto w-full max-w-2xl rounded-2xl border border-fail/30 bg-fail-soft p-8">
        <h1 ref={failedHeading} tabIndex={-1} className="text-xl font-semibold text-fail focus:outline-none">
          The check could not be completed
        </h1>
        <p className="mt-2 text-ink">{job.error ?? (job.status === 'done' ? 'The server finished without a verdict.' : 'Unknown error.')} The uploaded files have been deleted from the server.</p>
        <button type="button" onClick={newCase} className="mt-6 rounded-xl bg-brand px-5 py-2.5 font-semibold text-white hover:bg-brand/90">
          Start again
        </button>
      </section>
    )
  } else if (uploadProgress !== null || jobId) {
    screen = (
      <ProgressScreen
        uploadProgress={uploadProgress}
        job={job}
        reconnecting={reconnecting}
        startedAt={startedAt}
        onCancel={cancel}
        cancelling={cancelling}
        cancelError={cancelError}
        stalled={stalled}
        onKeepWaiting={keepWaiting}
        onStartAgain={newCase}
      />
    )
  } else {
    screen = <UploadScreen draft={draft} onChange={setDraft} onSubmit={start} error={error} ignored={ignored} />
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-line bg-white print:hidden">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-4 sm:px-6">
          <div className="flex items-center gap-3">
            <img src="/favicon.svg" alt="" className="h-8 w-8" />
            <div>
              <p className="font-semibold leading-tight">HKLV Document Check</p>
              <p className="text-xs text-muted">Rulebook v2.5</p>
            </div>
          </div>
          <ServerBadge status={server} />
        </div>
      </header>
      <main className="flex-1 px-4 py-10 sm:px-6 print:p-0">{screen}</main>
      <footer className="px-4 py-6 text-center text-xs text-muted print:hidden">
        Files are processed on this computer and deleted after each check.
      </footer>
    </div>
  )
}

function ServerBadge({ status }: { status: 'checking' | 'ready' | 'loading' | 'offline' }) {
  const look = {
    checking: ['bg-line', 'Connecting…'],
    ready: ['bg-pass', 'Server ready'],
    loading: ['bg-flag', 'Server starting…'],
    offline: ['bg-fail', 'Server offline'],
  }[status]
  return (
    <span className="flex items-center gap-2 text-sm text-muted" role="status">
      <span className={`h-2.5 w-2.5 rounded-full ${look[0]}`} aria-hidden />
      {look[1]}
    </span>
  )
}

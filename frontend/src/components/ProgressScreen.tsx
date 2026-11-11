import { useEffect, useRef, useState } from 'react'

import type { Job } from '../api'
import { formatDuration, formatEta } from '../lib/time'

type Step = 'upload' | 'waiting' | 'reading' | 'checking' | 'verdict'

const STEPS: { id: Step; label: string }[] = [
  { id: 'upload', label: 'Upload' },
  { id: 'waiting', label: 'Queue' },
  { id: 'reading', label: 'Read pages' },
  { id: 'checking', label: 'Check rules' },
  { id: 'verdict', label: 'Verdict' },
]

interface Props {
  /** 0..1 while the files are being sent; null once the job exists. */
  uploadProgress: number | null
  job: Job | null
  reconnecting: boolean
  startedAt: number
  onCancel: () => void
  cancelling: boolean
  /** Why the last cancel didn't work (e.g. the pages started being read meanwhile). */
  cancelError: string | null
  /** Polling gave up after repeated failures; why. */
  stalled: string | null
  onKeepWaiting: () => void
  onStartAgain: () => void
}

function currentStep(uploadProgress: number | null, job: Job | null): Step {
  if (uploadProgress !== null) return 'upload'
  if (!job) return 'waiting' // resuming after a page refresh: the upload is long done
  if (job.status === 'done' || job.status === 'failed') return 'verdict'
  if (job.stage === 'checking') return 'checking'
  if (job.status === 'running') return 'reading'
  return 'waiting'
}

export function ProgressScreen({
  uploadProgress,
  job,
  reconnecting,
  startedAt,
  onCancel,
  cancelling,
  cancelError,
  stalled,
  onKeepWaiting,
  onStartAgain,
}: Props) {
  const [now, setNow] = useState(() => Date.now())
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => heading.current?.focus(), [])
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])

  const step = currentStep(uploadProgress, job)
  const stepIndex = STEPS.findIndex((s) => s.id === step)
  const stepLabel = STEPS[stepIndex]?.label ?? ''
  const uploading = uploadProgress !== null
  const fraction = uploading ? uploadProgress * 0.03 : Math.max(0.03, job?.progress ?? 0)
  const percent = Math.round(fraction * 100)

  const sent = uploading && (uploadProgress ?? 0) >= 1
  let title = sent ? 'Preparing the files' : 'Uploading the files'
  let detail = sent ? 'Unpacking and checking the upload' : `${Math.round((uploadProgress ?? 0) * 100)}% sent`
  if (!uploading && !job) {
    title = reconnecting ? 'Lost contact with the server' : 'Reconnecting to the check'
    detail = reconnecting ? 'Retrying; the check continues on the server meanwhile' : 'Fetching its progress'
  } else if (!uploading && job) {
    title = job.message
    if (job.status === 'queued') {
      detail = job.queue_position ? `${job.queue_position} ${job.queue_position === 1 ? 'case is' : 'cases are'} ahead of this one` : 'Starting next'
    } else if (job.stage === 'reading') {
      detail = `Page ${Math.min(job.pages_done + 1, job.pages_total)} of ${job.pages_total}`
    } else if (job.stage === 'checking') {
      detail = 'Running the rule checks and online verification'
    }
  }
  // Once every byte is sent the server is already creating the job; cancelling then would
  // leave it running unseen, so wait for its id and cancel through the queue instead.
  const canCancel = (uploading && !sent) || job?.status === 'queued'
  const notCancellable = sent ? 'Starting…' : job ? "Can't be cancelled while reading" : ''

  return (
    <section className="mx-auto w-full max-w-2xl">
      <div className="rounded-2xl border border-line bg-white p-8 shadow-sm">
        <div className="flex items-center gap-4">
          <svg aria-hidden viewBox="0 0 24 24" className="h-9 w-9 shrink-0 animate-spin text-brand">
            <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" strokeOpacity="0.15" strokeWidth="3" />
            <path d="M22 12a10 10 0 00-10-10" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
          </svg>
          <div className="min-w-0">
            <h1 ref={heading} tabIndex={-1} className="text-xl font-semibold focus:outline-none">
              {title}
            </h1>
            <p className="text-muted">{detail}</p>
          </div>
          {/* Announce only the step, not every page read (a case runs for ~8 minutes). */}
          <p className="sr-only" aria-live="polite">
            Step {stepIndex + 1} of {STEPS.length}: {stepLabel}
          </p>
        </div>

        <div className="mt-7">
          <div
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent}
            aria-label="Verification progress"
            className="h-3 overflow-hidden rounded-full bg-surface"
          >
            <div className="progress-stripes h-full rounded-full bg-brand transition-[width] duration-700 ease-out" style={{ width: `${percent}%` }} />
          </div>
          <div className="mt-2 flex justify-between text-sm text-muted">
            <span>{percent}%</span>
            <span>
              {job?.eta_seconds != null && !uploading ? `${formatEta(job.eta_seconds)} left · ` : ''}
              {formatDuration((now - startedAt) / 1000)} elapsed
            </span>
          </div>
        </div>

        <ol className="mt-8 grid grid-cols-5 gap-2 text-center text-xs sm:text-sm">
          {STEPS.map((s, i) => {
            const state = i < stepIndex ? 'done' : i === stepIndex ? 'active' : 'todo'
            return (
              <li key={s.id} aria-current={state === 'active' ? 'step' : undefined} className="flex flex-col items-center gap-2">
                <span
                  className={[
                    'flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold',
                    state === 'done' && 'bg-brand text-white',
                    state === 'active' && 'bg-brand-soft text-brand ring-2 ring-brand',
                    state === 'todo' && 'bg-surface text-muted',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                >
                  {state === 'done' ? '✓' : i + 1}
                </span>
                <span className={state === 'todo' ? 'text-muted' : 'font-medium'}>{s.label}</span>
              </li>
            )
          })}
        </ol>

        {cancelError && (
          <p role="alert" className="mt-6 rounded-lg bg-flag-soft px-4 py-2 text-sm text-flag">
            {cancelError}
          </p>
        )}

        {stalled && (
          <div role="alert" className="mt-6 rounded-lg bg-fail-soft px-4 py-3 text-sm text-fail">
            <p>{stalled}</p>
            <div className="mt-3 flex gap-3">
              <button type="button" onClick={onKeepWaiting} className="rounded-lg bg-brand px-3 py-1.5 font-semibold text-white hover:bg-brand/90">
                Keep waiting
              </button>
              <button type="button" onClick={onStartAgain} className="rounded-lg px-3 py-1.5 font-medium text-ink hover:bg-surface">
                Start again
              </button>
            </div>
          </div>
        )}

        {reconnecting && job && (
          <p role="status" className="mt-6 rounded-lg bg-flag-soft px-4 py-2 text-sm text-flag">
            Lost contact with the server; retrying. The check continues on the server meanwhile.
          </p>
        )}

        <div className="mt-8 flex items-center justify-between border-t border-line pt-5 text-sm">
          <p className="text-muted">You can keep this tab open; the result appears here when ready.</p>
          {canCancel ? (
            <button
              type="button"
              onClick={onCancel}
              disabled={cancelling}
              className="rounded-lg px-3 py-1.5 font-medium text-muted hover:bg-surface hover:text-ink disabled:opacity-50"
            >
              {cancelling ? 'Cancelling…' : 'Cancel'}
            </button>
          ) : (
            <span className="text-muted" title="Pages that are being read can't be stopped half-way">
              {notCancellable}
            </span>
          )}
        </div>
      </div>
    </section>
  )
}

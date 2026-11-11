import { useEffect, useRef, useState } from 'react'

import { ApiError, getJob, type Job } from '../api'

const POLL_MS = 2000
const MAX_BACKOFF_MS = 30000

export interface Polling {
  job: Job | null
  /** The server is unreachable right now; polling keeps retrying with back-off. */
  reconnecting: boolean
}

interface State extends Polling {
  jobId: string | null
}

/** Poll GET /jobs/{id} every 2 s until the job is done or failed. Network hiccups never
 * lose the job: the server keeps working, so we retry with back-off. If the server no longer
 * knows the job (expired, deleted, server restarted), `onGone` is called and polling stops. */
export function useJobPolling(jobId: string | null, onGone: (message: string) => void): Polling {
  const [state, setState] = useState<State>({ jobId: null, job: null, reconnecting: false })
  const onGoneRef = useRef(onGone)
  useEffect(() => {
    onGoneRef.current = onGone
  })

  useEffect(() => {
    if (!jobId) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let failures = 0
    const controller = new AbortController()

    const poll = async () => {
      try {
        const job = await getJob(jobId, controller.signal)
        if (cancelled) return
        failures = 0
        setState({ jobId, job, reconnecting: false })
        if (job.status === 'done' || job.status === 'failed') return
        timer = setTimeout(poll, POLL_MS)
      } catch (e) {
        if (cancelled || (e as Error).name === 'AbortError') return
        if (e instanceof ApiError && e.status === 404) {
          onGoneRef.current(
            'This check is no longer on the server (verdicts are kept for one hour, and are lost if the server restarts).',
          )
          return
        }
        failures += 1
        setState((s) => ({ ...s, jobId, reconnecting: true }))
        timer = setTimeout(poll, Math.min(MAX_BACKOFF_MS, POLL_MS * 2 ** Math.min(failures, 4)))
      }
    }
    poll()
    return () => {
      cancelled = true
      controller.abort()
      if (timer) clearTimeout(timer)
    }
  }, [jobId])

  // State left over from a previous job is never shown for a new one.
  if (!jobId || state.jobId !== jobId) return { job: null, reconnecting: false }
  return { job: state.job, reconnecting: state.reconnecting }
}

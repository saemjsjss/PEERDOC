import { useEffect, useRef, useState } from 'react'

import { API_HEADERS, ApiError, getJob, type Job } from '../api'

const POLL_MS = 2000
const MAX_BACKOFF_MS = 30000
/** After this long without one good answer, stop and let the user decide. */
export const GIVE_UP_MS = 5 * 60 * 1000

export interface Polling {
  job: Job | null
  /** The server is unreachable right now; polling keeps retrying with back-off. */
  reconnecting: boolean
  /** Polling has failed for GIVE_UP_MS and stopped; why. `keepWaiting` starts it again. */
  stalled: string | null
  keepWaiting: () => void
}

interface State {
  jobId: string | null
  job: Job | null
  reconnecting: boolean
  stalled: string | null
}

const GONE =
  'This check is no longer on the server (verdicts are kept for one hour, and are lost if the server restarts).'
const RESTARTED = 'The server restarted; please upload again.'

function stalledMessage(status: number): string {
  if (status === 0) {
    return 'The verification server could not be reached for 5 minutes. It may have stopped, or this computer may be offline.'
  }
  return `The server has been answering with an error (${status}) for 5 minutes.`
}

/** The id of the server process now running, if it reports one (null if unknown). */
async function currentServerId(): Promise<string | null> {
  try {
    const r = await fetch('/health', { cache: 'no-store', headers: API_HEADERS })
    const body = (await r.json()) as { server_id?: unknown }
    return typeof body.server_id === 'string' ? body.server_id : null
  } catch {
    return null
  }
}

/** Poll GET /jobs/{id} every 2 s until the job is done or failed. Network hiccups never
 * lose the job: the server keeps working, so we retry with back-off; after 5 minutes of
 * failures polling stops and `stalled` says why. If the server no longer knows the job
 * (expired, deleted, server restarted), `onGone` is called and polling stops. */
export function useJobPolling(jobId: string | null, onGone: (message: string) => void): Polling {
  const [state, setState] = useState<State>({ jobId: null, job: null, reconnecting: false, stalled: null })
  const onGoneRef = useRef(onGone)
  const resumeRef = useRef<(() => void) | null>(null)
  useEffect(() => {
    onGoneRef.current = onGone
  })

  useEffect(() => {
    if (!jobId) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let failures = 0
    let firstFailureAt = 0
    let serverId: string | undefined
    const controller = new AbortController()

    const poll = async () => {
      try {
        const job = await getJob(jobId, controller.signal)
        if (cancelled) return
        failures = 0
        serverId = job.server_id ?? serverId
        setState({ jobId, job, reconnecting: false, stalled: null })
        if (job.status === 'done' || job.status === 'failed') return
        timer = setTimeout(poll, POLL_MS)
      } catch (e) {
        if (cancelled || (e as Error).name === 'AbortError') return
        if (e instanceof ApiError && e.status === 404) {
          const now = serverId ? await currentServerId() : null
          if (cancelled) return
          onGoneRef.current(now && now !== serverId ? RESTARTED : GONE)
          return
        }
        if (failures === 0) firstFailureAt = Date.now()
        failures += 1
        if (Date.now() - firstFailureAt >= GIVE_UP_MS) {
          const status = e instanceof ApiError ? e.status : 0
          setState((s) => ({ ...s, jobId, reconnecting: false, stalled: stalledMessage(status) }))
          timer = undefined
          return
        }
        setState((s) => ({ ...s, jobId, reconnecting: true }))
        timer = setTimeout(poll, Math.min(MAX_BACKOFF_MS, POLL_MS * 2 ** Math.min(failures, 4)))
      }
    }
    resumeRef.current = () => {
      if (cancelled || timer) return
      failures = 0
      setState((s) => ({ ...s, reconnecting: true, stalled: null }))
      poll()
    }
    poll()
    return () => {
      cancelled = true
      resumeRef.current = null
      controller.abort()
      if (timer) clearTimeout(timer)
    }
  }, [jobId])

  const keepWaiting = () => resumeRef.current?.()

  // State left over from a previous job is never shown for a new one.
  if (!jobId || state.jobId !== jobId) return { job: null, reconnecting: false, stalled: null, keepWaiting }
  return { job: state.job, reconnecting: state.reconnecting, stalled: state.stalled, keepWaiting }
}

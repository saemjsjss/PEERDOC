import { useEffect, useRef } from 'react'

import type { Outcome, Verdict } from '../api'

const STYLE: Record<Outcome, { box: string; badge: string; title: string; text: string }> = {
  PASS: { box: 'border-pass/30 bg-pass-soft', badge: 'bg-pass', title: 'text-pass', text: 'All checks passed.' },
  FLAG: { box: 'border-flag/30 bg-flag-soft', badge: 'bg-flag', title: 'text-flag', text: 'Needs manual review.' },
  FAIL: { box: 'border-fail/30 bg-fail-soft', badge: 'bg-fail', title: 'text-fail', text: 'At least one check failed.' },
}

/** The final verdict, shown prominently. The full list of checks comes next. */
export function VerdictSummary({ verdict, onNewCase }: { verdict: Verdict; onNewCase: () => void }) {
  const s = STYLE[verdict.outcome]
  // After minutes of waiting, move focus (and screen readers) straight to the verdict.
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    heading.current?.focus()
  }, [])
  return (
    <section className="mx-auto w-full max-w-3xl">
      <div className={`rounded-2xl border p-8 ${s.box}`}>
        <p className="text-sm font-medium uppercase tracking-wider text-muted">Final verdict · {verdict.case_id}</p>
        <h1 ref={heading} tabIndex={-1} className="mt-3 flex flex-wrap items-center gap-4 focus:outline-none">
          <span className={`rounded-xl px-5 py-2 text-3xl font-bold tracking-wide text-white ${s.badge}`}>{verdict.outcome}</span>
          <span className={`text-lg font-semibold ${s.title}`}>{s.text}</span>
        </h1>
        <dl className="mt-6 grid grid-cols-3 gap-3 text-center">
          <div className="rounded-xl bg-white/70 p-3">
            <dt className="text-sm text-muted">Passed</dt>
            <dd className="text-2xl font-semibold text-pass">{verdict.counts.passed}</dd>
          </div>
          <div className="rounded-xl bg-white/70 p-3">
            <dt className="text-sm text-muted">Flagged</dt>
            <dd className="text-2xl font-semibold text-flag">{verdict.counts.flagged}</dd>
          </div>
          <div className="rounded-xl bg-white/70 p-3">
            <dt className="text-sm text-muted">Failed</dt>
            <dd className="text-2xl font-semibold text-fail">{verdict.counts.failed}</dd>
          </div>
        </dl>
        <p className="mt-4 text-sm text-muted">
          Evaluated on {verdict.evaluation_date}. The list of every check with its reason is the next screen to build.
        </p>
      </div>
      <div className="mt-6 flex justify-end">
        <button
          type="button"
          onClick={onNewCase}
          className="rounded-xl bg-brand px-6 py-3 font-semibold text-white shadow-sm hover:bg-brand/90 focus:outline-none focus-visible:ring-4 focus-visible:ring-brand/30"
        >
          Check another case
        </button>
      </div>
    </section>
  )
}

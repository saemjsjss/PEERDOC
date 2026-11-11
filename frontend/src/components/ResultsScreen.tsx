import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { flushSync } from 'react-dom'

import type { Outcome, RuleResult, Verdict } from '../api'
import { OUTCOME_STYLE } from '../lib/outcomes'
import { groupResults, problemsFirst, ruleTitle, type Filter } from '../lib/rules'
import { CheckRow } from './CheckRow'

const VERDICT_STYLE: Record<Outcome, { box: string; badge: string; title: string; text: string }> = {
  PASS: { box: 'border-pass/30 bg-pass-soft', badge: 'bg-pass', title: 'text-pass', text: 'All checks passed.' },
  FLAG: { box: 'border-flag/30 bg-flag-soft', badge: 'bg-flag', title: 'text-flag', text: 'Needs manual review.' },
  FAIL: { box: 'border-fail/30 bg-fail-soft', badge: 'bg-fail', title: 'text-fail', text: 'At least one check failed.' },
}

const FILTERS: { id: Filter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'FAIL', label: 'Failed' },
  { id: 'FLAG', label: 'Flagged' },
  { id: 'PASS', label: 'Passed' },
]

const FOCUS = 'focus:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2'

function matches(r: RuleResult, q: string): boolean {
  return [r.rule_id, ruleTitle(r.rule_id), r.reason, ...r.evidence.map((e) => `${e.doc_id} ${e.field} ${e.value ?? ''}`)]
    .join(' ')
    .toLowerCase()
    .includes(q)
}

function countOutcomes(results: RuleResult[]): Record<Filter, number> {
  const c: Record<Filter, number> = { all: results.length, FAIL: 0, FLAG: 0, PASS: 0 }
  for (const r of results) c[r.outcome] += 1
  return c
}

interface Props {
  verdict: Verdict
  onNewCase: () => void
}

export function ResultsScreen({ verdict, onNewCase }: Props) {
  const [filter, setFilter] = useState<Filter>('all')
  const [query, setQuery] = useState('')
  const [expandAll, setExpandAll] = useState(false)
  const [printing, setPrinting] = useState(false)
  const heading = useRef<HTMLHeadingElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const searchId = useId()
  const s = VERDICT_STYLE[verdict.outcome]

  // After minutes of waiting, move focus (and screen readers) straight to the verdict.
  useEffect(() => {
    heading.current?.focus()
  }, [])

  // Paper always gets every check with all its evidence, whatever is filtered, searched or
  // collapsed on screen. The browser snapshots the page right after 'beforeprint', so the
  // print state must be rendered synchronously (flushSync); print CSS in index.css also
  // opens every <details> as a backstop.
  useEffect(() => {
    const before = () => flushSync(() => setPrinting(true))
    const after = () => setPrinting(false)
    window.addEventListener('beforeprint', before)
    window.addEventListener('afterprint', after)
    return () => {
      window.removeEventListener('beforeprint', before)
      window.removeEventListener('afterprint', after)
    }
  }, [])

  function print() {
    flushSync(() => setPrinting(true))
    window.print()
  }

  const total = verdict.results.length
  const problems = useMemo(() => problemsFirst([...verdict.failures, ...verdict.flags]), [verdict])

  const q = printing ? '' : query.trim().toLowerCase()
  const matching = useMemo(() => (q ? verdict.results.filter((r) => matches(r, q)) : verdict.results), [verdict, q])
  const tabCounts = useMemo(() => countOutcomes(matching), [matching])
  const groups = useMemo(() => groupResults(matching, printing ? 'all' : filter), [matching, filter, printing])
  const shown = groups.reduce((n, g) => n + g.results.length, 0)

  // Announce the number of shown checks once typing pauses, not on every keystroke.
  const [announced, setAnnounced] = useState(shown)
  useEffect(() => {
    if (printing) return
    const t = setTimeout(() => setAnnounced(shown), 600)
    return () => clearTimeout(t)
  }, [shown, printing])

  const verdictCounts: Record<Outcome, number> = {
    PASS: verdict.counts.passed,
    FLAG: verdict.counts.flagged,
    FAIL: verdict.counts.failed,
  }

  function showOnly(f: Filter) {
    setFilter(f)
    setQuery('')
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    listRef.current?.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
  }

  return (
    <section className="mx-auto w-full max-w-4xl">
      {/* --- verdict --- */}
      <div className={`rounded-2xl border p-6 sm:p-8 ${s.box}`}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-sm font-medium uppercase tracking-wider text-muted">
              Final verdict · {verdict.case_id} · evaluated {verdict.evaluation_date}
            </p>
            <h1 ref={heading} tabIndex={-1} className="mt-3 flex flex-wrap items-center gap-4 focus:outline-none">
              <span className={`rounded-xl px-5 py-2 text-3xl font-bold tracking-wide text-white ${s.badge}`}>{verdict.outcome}</span>
              <span className={`text-lg font-semibold ${s.title}`}>{s.text}</span>
            </h1>
          </div>
          <div className="flex gap-2 print:hidden">
            <button type="button" onClick={print} className={`rounded-lg border border-line bg-white px-3 py-2 text-sm font-medium hover:bg-surface ${FOCUS}`}>
              Print
            </button>
            <button type="button" onClick={onNewCase} className={`rounded-lg bg-brand px-3 py-2 text-sm font-semibold text-white hover:bg-brand/90 ${FOCUS}`}>
              Check another case
            </button>
          </div>
        </div>
        <div className="mt-6 grid grid-cols-3 gap-3 text-center">
          {(['PASS', 'FLAG', 'FAIL'] as const).map((o) => (
            <button
              key={o}
              type="button"
              onClick={() => showOnly(o)}
              aria-label={`${OUTCOME_STYLE[o].label} ${verdictCounts[o]}, show these checks`}
              className={`rounded-xl bg-white/75 p-3 transition hover:bg-white ${FOCUS}`}
            >
              <span className="block text-sm text-muted">{OUTCOME_STYLE[o].label}</span>
              <span className={`block text-2xl font-semibold ${OUTCOME_STYLE[o].text}`}>{verdictCounts[o]}</span>
            </button>
          ))}
        </div>
      </div>

      {/* --- what needs attention, with the exact reasons --- */}
      {problems.length > 0 && (
        <div className="mt-6 overflow-hidden rounded-2xl border border-line bg-white">
          <h2 className="border-b border-line px-5 py-3 font-semibold">
            Needs attention <span className="font-normal text-muted">({problems.length})</span>
          </h2>
          <ul className="divide-y divide-line">
            {problems.map((r, i) => (
              <CheckRow key={`p-${r.rule_id}-${i}`} result={r} expanded printing={printing} />
            ))}
          </ul>
        </div>
      )}

      {/* --- every check --- */}
      <div ref={listRef} className="mt-8 scroll-mt-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 className="text-lg font-semibold">All checks</h2>
          <div className="flex flex-wrap items-center gap-2 print:hidden">
            <label htmlFor={searchId} className="sr-only">
              Search the checks
            </label>
            <input
              id={searchId}
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search checks, reasons, documents"
              className="w-60 max-w-full rounded-lg border border-line bg-white px-3 py-1.5 text-sm focus:border-brand focus:outline-none focus-visible:ring-2 focus-visible:ring-brand"
            />
            <button type="button" onClick={() => setExpandAll((v) => !v)} className={`rounded-lg px-2 py-1.5 text-sm text-muted hover:bg-white hover:text-ink ${FOCUS}`}>
              {expandAll ? 'Hide evidence' : 'Show all evidence'}
            </button>
          </div>
        </div>

        <div role="group" aria-label="Filter checks by outcome" className="mt-3 flex flex-wrap gap-2 print:hidden">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              aria-pressed={filter === f.id}
              onClick={() => setFilter(f.id)}
              className={[
                'rounded-full border px-3 py-1 text-sm transition',
                FOCUS,
                filter === f.id ? 'border-brand bg-brand text-white' : 'border-line bg-white text-ink hover:border-brand/50',
              ].join(' ')}
            >
              {f.label} <span className={filter === f.id ? 'text-white/85' : 'text-muted'}>{tabCounts[f.id]}</span>
            </button>
          ))}
        </div>

        <p className="sr-only" aria-live="polite">
          {announced} of {total} checks shown
        </p>

        {groups.length === 0 ? (
          <p className="mt-6 rounded-2xl border border-line bg-white px-5 py-8 text-center text-muted">No checks match.</p>
        ) : (
          <div className="mt-4 space-y-4">
            {groups.map((g) => (
              <section key={g.section.id} aria-labelledby={`sec-${g.section.id}`} className="overflow-hidden rounded-2xl border border-line bg-white break-inside-avoid-page">
                <h3 id={`sec-${g.section.id}`} className="flex flex-wrap items-center justify-between gap-2 border-b border-line bg-surface/60 px-5 py-2.5 text-sm">
                  <span className="font-semibold">{g.section.title}</span>
                  <span className="flex gap-3 text-xs">
                    {g.counts.PASS > 0 && <span className="text-pass">{g.counts.PASS} passed</span>}
                    {g.counts.FLAG > 0 && <span className="text-flag">{g.counts.FLAG} flagged</span>}
                    {g.counts.FAIL > 0 && <span className="text-fail">{g.counts.FAIL} failed</span>}
                  </span>
                </h3>
                <ul className="divide-y divide-line">
                  {g.results.map((r, i) => (
                    <CheckRow key={`${r.rule_id}-${i}`} result={r} expanded={expandAll} printing={printing} />
                  ))}
                </ul>
              </section>
            ))}
          </div>
        )}
      </div>

      <CaseDetails verdict={verdict} printing={printing} />
    </section>
  )
}

/** What was uploaded, how each page was classified, and the online checks. */
function CaseDetails({ verdict, printing }: { verdict: Verdict; printing: boolean }) {
  const { files, pages, online } = verdict
  return (
    // Re-keyed when printing starts, so it opens even if the user closed it by hand.
    <details key={printing ? 'print' : 'screen'} open={printing || undefined} className="mt-8 rounded-2xl border border-line bg-white">
      <summary className={`cursor-pointer select-none rounded-2xl px-5 py-3 ${FOCUS}`}>
        <h2 className="inline font-semibold">Files, pages and online checks</h2>
        <span className="ml-2 text-muted">
          {files.accepted.length} files · {pages.length} pages
          {files.ignored.length + files.ignored_more > 0 ? ` · ${files.ignored.length + files.ignored_more} ignored` : ''}
        </span>
      </summary>
      <div className="space-y-6 border-t border-line px-5 py-4 text-sm">
        {online.length > 0 && (
          <div>
            <h3 className="font-medium">Online checks</h3>
            <ul className="mt-2 space-y-1">
              {online.map((o) => (
                <li key={o.doc_id} className="break-words">
                  <span className="font-mono text-xs text-muted">{o.doc_id}</span>{' '}
                  <span className={o.status === 'VERIFIED' ? 'text-pass' : o.status === 'NOT_FOUND' ? 'text-fail' : 'text-flag'}>
                    {o.status ?? 'not checked'}
                  </span>
                  {o.detail && <span className="text-muted"> · {o.detail}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
        {(files.ignored.length > 0 || files.ignored_more > 0) && (
          <div>
            <h3 className="font-medium">Ignored files</h3>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              {files.ignored.map((f) => (
                <li key={f.name} className="break-all">
                  {f.name} <span className="break-normal text-muted">({f.reason})</span>
                </li>
              ))}
              {files.ignored_more > 0 && <li className="text-muted">and {files.ignored_more} more</li>}
            </ul>
          </div>
        )}
        <div>
          <h3 className="font-medium">Pages (classified by their content)</h3>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-left">
              <thead className="text-xs uppercase tracking-wide text-muted">
                <tr>
                  <th className="py-1 pr-3 font-medium">Page</th>
                  <th className="py-1 pr-3 font-medium">Recognised as</th>
                  <th className="py-1 pr-3 font-medium">Document</th>
                  <th className="py-1 font-medium">File</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {pages.map((p) => (
                  <tr key={p.page_no}>
                    <td className="py-1.5 pr-3 tabular-nums">{p.page_no}</td>
                    <td className="py-1.5 pr-3">{p.kind === 'ignored' ? <span className="text-muted">not used</span> : p.kind.replace(/_/g, ' ')}</td>
                    <td className="py-1.5 pr-3 font-mono text-xs text-muted">{p.doc_id ?? '-'}</td>
                    <td className="break-all py-1.5 text-muted">
                      {p.source_file}
                      {p.file_page > 1 ? `, p.${p.file_page}` : ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </details>
  )
}

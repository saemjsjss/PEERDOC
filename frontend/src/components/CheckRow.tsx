import type { RuleResult } from '../api'
import { OUTCOME_STYLE } from '../lib/outcomes'
import { CONFIDENCE_THRESHOLD, fieldLabel, formatConfidence, ruleTitle } from '../lib/rules'

interface Props {
  result: RuleResult
  /** Show the evidence (document, field, value, page) without clicking. */
  expanded: boolean
  /** Printing: always show the evidence, even if the user collapsed it on screen. */
  printing?: boolean
}

/** One rule result: outcome, plain-language rule name, the engine's exact reason, evidence. */
export function CheckRow({ result, expanded, printing = false }: Props) {
  const s = OUTCOME_STYLE[result.outcome]
  const open = expanded || printing
  return (
    <li data-rule={result.rule_id} className={`px-5 py-4 ${s.row}`}>
      <div className="flex gap-3">
        <span
          className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-sm font-bold ${s.badge}`}
          aria-hidden
        >
          {s.icon}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span className="sr-only">{s.label}:</span>
            <span className="font-medium">{ruleTitle(result.rule_id)}</span>
            <span className="rounded bg-surface px-1.5 py-0.5 font-mono text-xs text-muted">{result.rule_id}</span>
          </div>
          <p className="mt-1 break-words text-sm leading-relaxed text-ink/85">{result.reason}</p>
          {result.evidence.length > 0 && (
            // Re-keyed when it should open (Show all evidence) and when printing starts or ends,
            // so it opens even if the user had closed this one by hand.
            <details key={`${open}-${printing}`} open={open || undefined} className="mt-2 text-sm">
              <summary className="cursor-pointer select-none rounded text-muted hover:text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-brand print:hidden">
                Evidence ({result.evidence.length})
              </summary>
              <ul className="mt-2 space-y-1 rounded-lg border border-line bg-white px-3 py-2">
                {result.evidence.map((e, i) => {
                  const low = e.confidence != null && e.confidence < CONFIDENCE_THRESHOLD
                  return (
                    <li key={i} className="flex flex-wrap gap-x-2">
                      <span className="text-muted">{e.doc_id}</span>
                      <span className="text-muted" aria-hidden>
                        ·
                      </span>
                      <span className="font-medium">{fieldLabel(e.field)}:</span>
                      <span className="break-all">{e.value ?? <em className="text-muted">not read</em>}</span>
                      {e.page != null && <span className="text-muted">(page {e.page})</span>}
                      {e.confidence != null && (
                        <span
                          className={low ? 'rounded bg-flag-soft px-1.5 text-xs font-medium text-flag' : 'text-xs text-muted'}
                          title="How sure the reader was of this value"
                        >
                          {low ? 'low confidence ' : 'confidence '}
                          {formatConfidence(e.confidence)}
                        </span>
                      )}
                    </li>
                  )
                })}
              </ul>
            </details>
          )}
        </div>
      </div>
    </li>
  )
}

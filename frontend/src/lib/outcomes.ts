import type { Outcome } from '../api'

export const OUTCOME_STYLE: Record<Outcome, { icon: string; badge: string; text: string; row: string; label: string }> = {
  PASS: { icon: '✓', badge: 'bg-pass-soft text-pass', text: 'text-pass', row: '', label: 'Passed' },
  FLAG: { icon: '!', badge: 'bg-flag-soft text-flag', text: 'text-flag', row: 'bg-flag-soft/40', label: 'Flagged' },
  FAIL: { icon: '✕', badge: 'bg-fail-soft text-fail', text: 'text-fail', row: 'bg-fail-soft/40', label: 'Failed' },
}

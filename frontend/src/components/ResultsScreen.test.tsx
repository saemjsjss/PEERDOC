import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { Verdict } from '../api'
import fixture from '../test/fixtures/verdict-flag.json'
import { ruleTitle } from '../lib/rules'
import { ResultsScreen } from './ResultsScreen'

// A fictional FLAG verdict produced by the real rules engine (scripts/make_ui_fixture.py).
const verdict = fixture as unknown as Verdict

function renderScreen(v: Verdict = verdict) {
  const onNewCase = vi.fn()
  Element.prototype.scrollIntoView = vi.fn()
  render(<ResultsScreen verdict={v} onNewCase={onNewCase} />)
  return { onNewCase, user: userEvent.setup() }
}

const rows = () => Array.from(document.querySelectorAll('li[data-rule]'))

describe('ResultsScreen', () => {
  it('shows the final verdict prominently, with focus on it', () => {
    renderScreen()
    const heading = screen.getByRole('heading', { level: 1 })
    expect(heading).toHaveTextContent('FLAG')
    expect(heading).toHaveTextContent('Needs manual review.')
    expect(heading).toHaveFocus()
    expect(screen.getByText(/fictional-0417/)).toBeInTheDocument()
  })

  it('lists what needs attention first, with the exact reasons', () => {
    renderScreen()
    const attention = screen.getByRole('heading', { name: /Needs attention/ }).parentElement!
    const items = attention.querySelectorAll('li[data-rule]')
    expect(items).toHaveLength(verdict.flags.length + verdict.failures.length)
    for (const r of verdict.flags) {
      expect(within(attention).getByText(r.reason)).toBeInTheDocument()
      expect(within(attention).getByText(ruleTitle(r.rule_id))).toBeInTheDocument()
    }
  })

  it('lists every check with its reason, grouped by rulebook section', () => {
    renderScreen()
    const all = screen.getByRole('heading', { name: 'All checks' }).closest('div')!.parentElement!
    expect(within(all).getAllByText(/^(REQ|PASSPORT|NID|BIRTH|FRC|BANK|TRADE|TIN|ACAD|TAX|CHAIN)/).length).toBeGreaterThanOrEqual(verdict.results.length)
    for (const title of ['Required documents', 'Passport and NIDs', 'Birth certificate', 'Academic documents', 'Financial chain']) {
      expect(screen.getByRole('heading', { name: new RegExp(title) })).toBeInTheDocument()
    }
    const passed = verdict.results.find((r) => r.outcome === 'PASS')!
    expect(screen.getAllByText(passed.reason).length).toBeGreaterThan(0)
  })

  it('filters by outcome from the tabs and from the counts', async () => {
    const { user } = renderScreen()
    await user.click(screen.getByRole('button', { name: /^Flagged \d+$/ }))
    // Needs-attention rows (3) + the filtered list (3)
    expect(rows()).toHaveLength(verdict.flags.length * 2)
    await user.click(screen.getByRole('button', { name: `Passed ${verdict.counts.passed}, show these checks` }))
    expect(screen.getByRole('button', { name: /^Passed \d+$/ })).toHaveAttribute('aria-pressed', 'true')
    expect(rows()).toHaveLength(verdict.counts.passed + verdict.flags.length)
  })

  it('searches rule names, reasons and evidence', async () => {
    const { user } = renderScreen()
    await user.type(screen.getByLabelText('Search the checks'), 'registration number')
    expect(screen.getByText(/of \d+ checks shown/)).toHaveTextContent(/^\d+ of 54 checks shown$/)
    await user.clear(screen.getByLabelText('Search the checks'))
    await user.type(screen.getByLabelText('Search the checks'), 'zzz-no-match')
    expect(screen.getByText('No checks match.')).toBeInTheDocument()
  })

  it('shows the evidence behind a check', async () => {
    const { user } = renderScreen()
    await user.click(screen.getByRole('button', { name: 'Show all evidence' }))
    const brn = verdict.flags.find((r) => r.rule_id === 'BIRTH-04')!
    const value = brn.evidence.find((e) => e.field === 'registration_number')!.value!
    expect(screen.getAllByText(value).length).toBeGreaterThan(0)
  })

  it('has Print and Check another case', async () => {
    const print = vi.spyOn(window, 'print').mockImplementation(() => undefined)
    const { user, onNewCase } = renderScreen()
    await user.click(screen.getByRole('button', { name: 'Print' }))
    expect(print).toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Check another case' }))
    expect(onNewCase).toHaveBeenCalled()
  })

  it('a clean PASS has no needs-attention box', () => {
    const pass: Verdict = {
      ...verdict,
      outcome: 'PASS',
      flags: [],
      failures: [],
      results: verdict.results.filter((r) => r.outcome === 'PASS'),
      counts: { passed: verdict.counts.passed, flagged: 0, failed: 0 },
    }
    renderScreen(pass)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('PASS')
    expect(screen.queryByRole('heading', { name: /Needs attention/ })).not.toBeInTheDocument()
  })

  it('shows files, pages and online checks', async () => {
    const { user } = renderScreen()
    const summary = screen.getByText('Files, pages and online checks')
    await user.click(summary)
    const details = within(summary.closest('details')!)
    expect(details.getByText(/notes\.txt/)).toBeInTheDocument()
    expect(details.getAllByText('VERIFIED').length).toBe(verdict.online.length)
  })
})

describe('evidence confidence', () => {
  it('marks the low-confidence reading that made a rule flag', () => {
    renderScreen()
    const attention = screen.getByRole('heading', { name: /Needs attention/ }).parentElement!
    const brn = attention.querySelector('li[data-rule="BIRTH-04"]') as HTMLElement
    expect(within(brn).getByText(/low confidence 0\.60/)).toBeInTheDocument()
  })
})

describe('printing', () => {
  it('puts every check with all its evidence on paper, whatever is filtered, searched or collapsed', async () => {
    const { user } = renderScreen()
    await user.click(screen.getByRole('button', { name: /^Flagged \d+$/ }))
    await user.type(screen.getByLabelText('Search the checks'), 'BIRTH-04')
    const attention = screen.getByRole('heading', { name: /Needs attention/ }).parentElement!
    const firstDetails = attention.querySelector('details') as HTMLDetailsElement
    firstDetails.open = false // collapsed by hand
    act(() => {
      window.dispatchEvent(new Event('beforeprint'))
    })
    // Synchronously after beforeprint (the browser snapshots right then):
    expect(rows()).toHaveLength(verdict.results.length + verdict.flags.length + verdict.failures.length)
    const details = Array.from(document.querySelectorAll('li[data-rule] details')) as HTMLDetailsElement[]
    expect(details.length).toBeGreaterThan(0)
    expect(details.every((d) => d.open)).toBe(true)
    expect((screen.getByText('Files, pages and online checks').closest('details') as HTMLDetailsElement).open).toBe(true)
    act(() => {
      window.dispatchEvent(new Event('afterprint'))
    })
    expect(rows()).toHaveLength(1 + verdict.flags.length) // the on-screen view is back
  })
})

describe('filter counts follow the search', () => {
  it('counts only the checks the search matches', async () => {
    const { user } = renderScreen()
    await user.type(screen.getByLabelText('Search the checks'), 'BIRTH-04')
    expect(screen.getByRole('button', { name: /^Flagged \d+$/ })).toHaveTextContent('Flagged 1')
    expect(screen.getByRole('button', { name: /^All \d+$/ })).toHaveTextContent('All 1')
  })
})

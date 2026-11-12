// Plain-language names for every rule the engine reports (rulebook.md v2.5 and the
// approved supplement in docs/rulebook-supplement-draft.md), and the section each belongs to.

import type { Outcome, RuleResult } from '../api'

export interface Section {
  id: string
  title: string
}

export const SECTIONS: Section[] = [
  { id: 'required', title: 'Required documents' },
  { id: 'identity', title: 'Passport and NIDs' },
  { id: 'birth', title: 'Birth certificate' },
  { id: 'death', title: 'Death certificate' },
  { id: 'frc', title: 'Family relationship certificate' },
  { id: 'bank', title: 'Bank solvency and statement' },
  { id: 'income', title: 'Trade licence / employment' },
  { id: 'tin', title: 'TIN certificate' },
  { id: 'chain', title: 'Financial chain' },
  { id: 'academic', title: 'Academic documents' },
  { id: 'tax', title: 'Income tax (optional)' },
  { id: 'language', title: 'IELTS / TOPIK (optional)' },
  { id: 'stamps', title: 'Notary and translation dates' },
  { id: 'other', title: 'Other checks' },
]

const TITLES: Record<string, string> = {
  'REQ-01': 'Passport submitted',
  'REQ-02': 'Photo submitted',
  'REQ-03': 'Birth certificate submitted',
  'REQ-04': 'Family relationship certificate submitted',
  'REQ-05': 'Bank solvency letter and statement submitted',
  'REQ-06': 'Trade licence or employment certificate submitted',
  'REQ-07': 'TIN certificate submitted',
  'REQ-08': "Father's NID or death certificate submitted",
  'REQ-09': "Mother's NID or death certificate submitted",
  'REQ-10': 'Optional documents',
  'PASSPORT-01': 'Passport valid for 12+ months; MRZ matches the print',
  'NID-ASSIGN': 'NID belongs to the student, father or mother',
  'NID-01': 'NID has an English translation',
  'NID-02': 'NID is notarised',
  'NID-03': 'NID number on card matches the translation',
  'BIRTH-01': 'Birth certificate in English or translated',
  'BIRTH-02': 'Birth certificate is notarised',
  'BIRTH-03': 'Date of birth matches the passport (year only if translated)',
  'BIRTH-04': 'Registration number starts with the birth year',
  'BIRTH-05': 'Birth certificate name matches the passport',
  'DEATH-01': 'Death certificate is for the father or mother',
  'DEATH-02': 'Death certificate in English or translated',
  'DEATH-03': 'Death certificate is notarised',
  'DEATH-04': 'Date of death is readable',
  'DEATH-05': 'No document shows the deceased parent as alive later',
  'FRC-01': 'Issued by a Union Parishad, Pourashava or City Corporation',
  'FRC-02': "Lists the student (self) with the student's name",
  'FRC-03': "Lists the father and mother with their names",
  'FRC-04': 'Issued within the last 3 months',
  'FRC-05': 'Family certificate is notarised',
  'BANK-01': 'Account holder is the father or mother',
  'BANK-02': 'Account number matches the statement',
  'BANK-03': 'Solvency date matches the statement date',
  'BANK-04': 'Minimum balance (not checked by rule)',
  'BANK-05': 'Solvency letter states the amount in USD and BDT',
  'TRADE-01': 'Trade licence in English or translated',
  'TRADE-02': 'Trade licence is notarised',
  'TRADE-03': 'Trade licence valid this fiscal year (to 30 June) or issued since 1 July',
  'TRADE-04': 'Trade licence owner is the father or mother',
  'EMP-01': 'Employment certificate in English or translated',
  'EMP-02': 'Employment certificate is notarised',
  'EMP-03': 'Employment certificate issued within 3 months',
  'EMP-04': 'States current employment',
  'EMP-05': 'Employee is the father or mother',
  'TIN-01': 'TIN QR code can be read',
  'TIN-02': 'Printed TIN matches the QR code',
  'TIN-03': 'Taxpayer is the trade licence owner',
  'CHAIN-02': 'TIN and trade licence belong to the same parent',
  'CHAIN-03': 'TIN is not in the student’s name',
  'ACAD-01': 'e-Apostille verified on the official register',
  'ACAD-02': 'Certificate and transcript for each level',
  'ACAD-03': 'Valid equivalency track (e.g. SSC + HSC)',
  'ACAD-04': "Names match the student; SSC date of birth matches",
  'ACAD-05': 'Certificate and transcript are notarised',
  'ACAD-06': 'SSC and HSC registration numbers match',
  'STAMP-01': 'Notary and translation dates within 3 months',
  'TAX-01': 'Income tax documents (optional)',
  'TAX-03': 'Income shown at least 5,000,000 BDT',
  'TAX-04': 'Challan verified online',
  'LANG-01': 'Test taken within the last 2 years',
  'LANG-02': "Name and date of birth match the student",
  'ENGINE-COVERAGE': 'Rules not yet implemented',
}

const SECTION_OF_PREFIX: [string, string][] = [
  ['REQ-', 'required'],
  ['PASSPORT-', 'identity'],
  ['NID-', 'identity'],
  ['BIRTH-', 'birth'],
  ['DEATH-', 'death'],
  ['FRC-', 'frc'],
  ['BANK-', 'bank'],
  ['TRADE-', 'income'],
  ['EMP-', 'income'],
  ['TIN-', 'tin'],
  ['CHAIN-', 'chain'],
  ['ACAD-', 'academic'],
  ['TAX-', 'tax'],
  ['LANG-', 'language'],
  ['STAMP-', 'stamps'],
]

export function ruleTitle(ruleId: string): string {
  return TITLES[ruleId] ?? ruleId
}

export function sectionOf(ruleId: string): string {
  return SECTION_OF_PREFIX.find(([prefix]) => ruleId.startsWith(prefix))?.[1] ?? 'other'
}

const SEVERITY: Record<Outcome, number> = { FAIL: 0, FLAG: 1, PASS: 2 }

export type Filter = 'all' | Outcome

export interface SectionGroup {
  section: Section
  results: RuleResult[]
  counts: Record<Outcome, number>
}

/** Results grouped by section (rulebook order), filtered by outcome. Within a section the
 * original engine order is kept; sections without matching results are dropped. */
export function groupResults(results: RuleResult[], filter: Filter): SectionGroup[] {
  return SECTIONS.map((section) => {
    const all = results.filter((r) => sectionOf(r.rule_id) === section.id)
    const counts: Record<Outcome, number> = { PASS: 0, FLAG: 0, FAIL: 0 }
    for (const r of all) counts[r.outcome] += 1
    return { section, results: filter === 'all' ? all : all.filter((r) => r.outcome === filter), counts }
  }).filter((g) => g.results.length > 0)
}

/** Problems first: FAIL, then FLAG, keeping engine order within each. */
export function problemsFirst(results: RuleResult[]): RuleResult[] {
  return results
    .map((r, i) => [r, i] as const)
    .sort((a, b) => SEVERITY[a[0].outcome] - SEVERITY[b[0].outcome] || a[1] - b[1])
    .map(([r]) => r)
}

/** "number_on_card" -> "number on card", "notary.stamp_present" -> "notary stamp present",
 * "notary.notary_text_present" -> "notary text present", "members[2].name" -> "member 3 name". */
export function fieldLabel(field: string): string {
  const parts = field.split('.')
  const [first, second] = parts
  if (first !== undefined && second?.startsWith(first)) parts.shift() // no "notary notary ..."
  return parts
    .join(' ')
    .replace(/(\w+)s\[(\d+)\]/g, (_m, word: string, i: string) => `${word} ${Number(i) + 1}`)
    .replace(/_/g, ' ')
}

/** The engine's default confidence threshold (DEFAULT_CONFIDENCE_THRESHOLD): below it a
 * reading is not trusted and its rule FLAGs. */
export const CONFIDENCE_THRESHOLD = 0.9

/** Two decimals, rounded down, so a value just below the threshold (0.8996) never shows as
 * "0.90" next to a "low confidence" label. */
export function formatConfidence(confidence: number): string {
  return (Math.floor(confidence * 100 + 1e-9) / 100).toFixed(2)
}

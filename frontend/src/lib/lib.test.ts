import { describe, expect, it } from 'vitest'

import { formatBytes, isAccepted, kindLabel, mergeFiles, totalBytes } from './files'
import { formatDuration, formatEta } from './time'

const file = (name: string, size = 10, lastModified = 1) => ({ name, size, lastModified }) as File

describe('files', () => {
  it('accepts what the server reads, case-insensitively', () => {
    for (const n of ['a.pdf', 'B.PDF', 'c.jpg', 'd.jpeg', 'e.png', 'f.tif', 'g.tiff', 'h.webp', 'i.bmp', 'case.zip']) {
      expect(isAccepted(file(n))).toBe(true)
    }
    for (const n of ['notes.txt', 'cv.docx', 'noext', 'archive.rar']) expect(isAccepted(file(n))).toBe(false)
  })

  it('merges selections without duplicates and reports unsupported files', () => {
    const a = file('a.pdf')
    const { files, rejected } = mergeFiles([a], [file('a.pdf'), file('b.pdf'), file('x.docx')])
    expect(files.map((f) => f.name)).toEqual(['a.pdf', 'b.pdf'])
    expect(rejected.map((f) => f.name)).toEqual(['x.docx'])
  })

  it('formats sizes and kinds', () => {
    expect(totalBytes([file('a', 1024), file('b', 2048)])).toBe(3072)
    expect(formatBytes(500)).toBe('500 B')
    expect(formatBytes(14134 * 1024)).toBe('13.8 MB')
    expect(kindLabel('x.zip')).toBe('ZIP')
    expect(kindLabel('x.PDF')).toBe('PDF')
    expect(kindLabel('x.jpg')).toBe('Image')
  })
})

describe('time', () => {
  it('formats durations', () => {
    expect(formatDuration(45)).toBe('45 s')
    expect(formatDuration(510)).toBe('8 min 30 s')
    expect(formatDuration(3900)).toBe('1 h 5 min')
  })

  it('rounds the estimate calmly', () => {
    expect(formatEta(30)).toBe('under a minute')
    expect(formatEta(510)).toBe('about 9 min')
    expect(formatEta(null)).toBe('')
  })
})

import { fieldLabel, groupResults, problemsFirst, ruleTitle, sectionOf } from './rules'

describe('rules', () => {
  it('names fields readably', () => {
    expect(fieldLabel('notary.notary_text_present')).toBe('notary text present')
    expect(fieldLabel('notary.stamp_present')).toBe('notary stamp present')
    expect(fieldLabel('number_on_card')).toBe('number on card')
    expect(fieldLabel('members[2].name')).toBe('member 3 name')
  })

  it('knows every rule family and falls back to the id', () => {
    expect(ruleTitle('BIRTH-04')).toBe('Registration number starts with the birth year')
    expect(ruleTitle('NEW-99')).toBe('NEW-99')
    expect(sectionOf('NID-ASSIGN')).toBe('identity')
    expect(sectionOf('EMP-03')).toBe('income')
    expect(sectionOf('NEW-99')).toBe('other')
  })

  it('groups by section in rulebook order and filters by outcome', () => {
    const r = (rule_id: string, outcome: 'PASS' | 'FLAG' | 'FAIL') => ({ rule_id, outcome, reason: '', evidence: [] })
    const results = [r('ACAD-01', 'PASS'), r('REQ-01', 'PASS'), r('BIRTH-04', 'FLAG'), r('REQ-02', 'FAIL')]
    expect(groupResults(results, 'all').map((g) => g.section.id)).toEqual(['required', 'birth', 'academic'])
    expect(groupResults(results, 'FLAG').map((g) => g.results.map((x) => x.rule_id))).toEqual([['BIRTH-04']])
    expect(problemsFirst(results).map((x) => x.rule_id)).toEqual(['REQ-02', 'BIRTH-04', 'ACAD-01', 'REQ-01'])
  })
})

import { formatConfidence } from './rules'

describe('confidence', () => {
  it('never rounds a low value up to the threshold', () => {
    expect(formatConfidence(0.8996)).toBe('0.89')
    expect(formatConfidence(0.6)).toBe('0.60')
    expect(formatConfidence(0.99)).toBe('0.99')
    expect(formatConfidence(1)).toBe('1.00')
  })
})

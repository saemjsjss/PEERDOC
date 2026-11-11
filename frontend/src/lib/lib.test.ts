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

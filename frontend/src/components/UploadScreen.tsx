import { useId, useRef, useState, type DragEvent, type KeyboardEvent } from 'react'

import {
  ACCEPT_ATTRIBUTE,
  formatBytes,
  kindLabel,
  MAX_UPLOAD_BYTES,
  mergeFiles,
  totalBytes,
} from '../lib/files'
import type { SubmitOptions } from '../api'
import type { Draft } from '../lib/draft'

interface Props {
  /** The selection lives in the parent, so it survives an upload error. */
  draft: Draft
  onChange: (draft: Draft) => void
  onSubmit: (files: File[], options: SubmitOptions) => void
  error: string | null
  ignored?: { name: string; reason: string }[]
}

export function UploadScreen({ draft, onChange, onSubmit, error, ignored = [] }: Props) {
  const { files, caseId, evaluationDate, online } = draft
  const setFiles = (next: File[]) => onChange({ ...draft, files: next })
  const setCaseId = (next: string) => onChange({ ...draft, caseId: next })
  const setEvaluationDate = (next: string) => onChange({ ...draft, evaluationDate: next })
  const setOnline = (next: boolean) => onChange({ ...draft, online: next })
  const [rejected, setRejected] = useState<string[]>([])
  const [dragging, setDragging] = useState(false)
  const [showOptions, setShowOptions] = useState(Boolean(caseId || evaluationDate || !online))
  const input = useRef<HTMLInputElement>(null)
  const dragDepth = useRef(0)
  const ids = { case: useId(), date: useId(), online: useId(), hint: useId() }

  const size = totalBytes(files)
  const tooBig = size > MAX_UPLOAD_BYTES

  function add(list: FileList | null) {
    if (!list?.length) return
    const merged = mergeFiles(files, Array.from(list))
    setFiles(merged.files)
    setRejected(merged.rejected.map((f) => f.name))
  }

  function onDrop(e: DragEvent) {
    e.preventDefault()
    dragDepth.current = 0
    setDragging(false)
    add(e.dataTransfer.files)
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      input.current?.click()
    }
  }

  function submit() {
    if (!files.length || tooBig) return
    onSubmit(files, { caseId, evaluationDate: evaluationDate || undefined, online })
  }

  return (
    <section className="mx-auto w-full max-w-3xl">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Check a student's documents</h1>
        <p className="mt-1 text-muted">
          Upload the case as one ZIP file, or select the PDFs and images. Every page is read and
          checked against Rulebook v2.5.
        </p>
      </div>

      <div
        role="button"
        tabIndex={0}
        aria-describedby={ids.hint}
        onClick={() => input.current?.click()}
        onKeyDown={onKey}
        onDragEnter={(e) => {
          e.preventDefault()
          dragDepth.current += 1
          setDragging(true)
        }}
        onDragOver={(e) => e.preventDefault()}
        onDragLeave={() => {
          dragDepth.current = Math.max(0, dragDepth.current - 1)
          if (dragDepth.current === 0) setDragging(false)
        }}
        onDrop={onDrop}
        className={[
          'flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-14 text-center transition-colors',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2',
          dragging ? 'border-brand bg-brand-soft' : 'border-line bg-white hover:border-brand/60 hover:bg-brand-soft/40',
        ].join(' ')}
      >
        <svg aria-hidden viewBox="0 0 48 48" className={`mb-4 h-12 w-12 ${dragging ? 'text-brand' : 'text-muted'}`}>
          <path
            d="M24 31V11m0 0l-8 8m8-8l8 8M10 30v5a4 4 0 004 4h20a4 4 0 004-4v-5"
            fill="none"
            stroke="currentColor"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <p className="text-lg font-medium">{dragging ? 'Drop the files to add them' : 'Drag and drop the ZIP or PDFs here'}</p>
        <p className="mt-1 text-muted">
          or <span className="font-medium text-brand underline underline-offset-4">browse your computer</span>
        </p>
        <p id={ids.hint} className="mt-4 text-sm text-muted">
          ZIP, PDF, JPG, PNG, TIFF or WebP · up to 150 MB in total
        </p>
        <input
          ref={input}
          type="file"
          multiple
          accept={ACCEPT_ATTRIBUTE}
          className="hidden"
          onChange={(e) => {
            add(e.target.files)
            e.target.value = ''
          }}
        />
      </div>

      {rejected.length > 0 && (
        <p role="alert" className="mt-3 rounded-lg bg-flag-soft px-4 py-2 text-sm text-flag">
          Not added (only ZIP, PDF and image files): {rejected.join(', ')}
        </p>
      )}

      {files.length > 0 && (
        <div className="mt-6 overflow-hidden rounded-2xl border border-line bg-white">
          <div className="flex items-center justify-between border-b border-line px-5 py-3 text-sm">
            <span className="font-medium">
              {files.length} {files.length === 1 ? 'file' : 'files'} · {formatBytes(size)}
            </span>
            <button type="button" onClick={() => setFiles([])} className="text-muted hover:text-ink">
              Clear all
            </button>
          </div>
          <ul className="max-h-72 divide-y divide-line overflow-y-auto">
            {files.map((file, i) => (
              <li key={`${file.name}-${i}`} className="flex items-center gap-3 px-5 py-2.5">
                <span className="w-12 shrink-0 rounded bg-surface py-0.5 text-center text-xs font-semibold text-muted">
                  {kindLabel(file.name)}
                </span>
                <span className="min-w-0 flex-1 truncate" title={file.name}>
                  {file.name}
                </span>
                <span className="shrink-0 text-sm text-muted">{formatBytes(file.size)}</span>
                <button
                  type="button"
                  aria-label={`Remove ${file.name}`}
                  onClick={() => setFiles(files.filter((_, j) => j !== i))}
                  className="shrink-0 rounded p-1 text-muted hover:bg-surface hover:text-ink"
                >
                  <svg aria-hidden viewBox="0 0 20 20" className="h-4 w-4">
                    <path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                  </svg>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-4">
        <button
          type="button"
          aria-expanded={showOptions}
          onClick={() => setShowOptions((v) => !v)}
          className="text-sm font-medium text-muted hover:text-ink"
        >
          {showOptions ? '▾' : '▸'} Options
        </button>
        {showOptions && (
          <div className="mt-3 grid gap-4 rounded-2xl border border-line bg-white p-5 sm:grid-cols-2">
            <label htmlFor={ids.case} className="text-sm">
              <span className="font-medium">Case reference</span>
              <input
                id={ids.case}
                value={caseId}
                maxLength={100}
                onChange={(e) => setCaseId(e.target.value)}
                placeholder="e.g. 2026-0417"
                className="mt-1 w-full rounded-lg border border-line px-3 py-2 focus:border-brand focus:outline-none"
              />
            </label>
            <label htmlFor={ids.date} className="text-sm">
              <span className="font-medium">Evaluation date</span>
              <input
                id={ids.date}
                type="date"
                value={evaluationDate}
                onChange={(e) => setEvaluationDate(e.target.value)}
                className="mt-1 w-full rounded-lg border border-line px-3 py-2 focus:border-brand focus:outline-none"
              />
              <span className="mt-1 block text-muted">Leave empty for today.</span>
            </label>
            <label htmlFor={ids.online} className="flex items-start gap-3 text-sm sm:col-span-2">
              <input
                id={ids.online}
                type="checkbox"
                checked={online}
                onChange={(e) => setOnline(e.target.checked)}
                className="mt-0.5 h-4 w-4 accent-brand"
              />
              <span>
                <span className="font-medium">Verify online</span>
                <span className="block text-muted">
                  Check e-Apostilles on apostille.mygov.bd and tax challans on the A-challan system.
                  Without this, those checks are flagged for manual review.
                </span>
              </span>
            </label>
          </div>
        )}
      </div>

      {(error || tooBig) && (
        <div role="alert" className="mt-4 rounded-lg bg-fail-soft px-4 py-3 text-sm text-fail">
          {tooBig ? 'The files are larger than 150 MB together. Remove some, or upload them in parts.' : error}
          {ignored.length > 0 && (
            <ul className="mt-2 list-disc pl-5">
              {ignored.map((i) => (
                <li key={i.name}>
                  {i.name}: {i.reason}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="mt-6 flex items-center justify-end gap-4">
        <p className="text-sm text-muted">A full case takes about 8 minutes.</p>
        <button
          type="button"
          onClick={submit}
          disabled={!files.length || tooBig}
          className="rounded-xl bg-brand px-6 py-3 font-semibold text-white shadow-sm transition hover:bg-brand/90 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-line disabled:text-muted"
        >
          Verify documents
        </button>
      </div>
    </section>
  )
}

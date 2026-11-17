# HKLV Document Check - web UI

React 19 + Vite + Tailwind CSS + TypeScript. Upload a case (a ZIP, or PDFs and images), follow
the progress while the server reads it, then see the verdict.

## Screens

1. **Upload**: drag and drop a ZIP or PDFs/images; options for case reference, evaluation
   date and online checks.
2. **Progress**: upload, queue, page-by-page reading, rule checks; time left.
3. **Results**: the final verdict (PASS / FLAG / FAIL) with counts; a "Needs attention" list
   of every failed and flagged check with the exact reason; then every check, grouped by
   rulebook section, filterable (all / failed / flagged / passed) and searchable, each with
   its evidence (document, field, value read, page, OCR confidence - values below 0.90 are
   marked, they are why a check flags). Files, page classification and online checks are
   in a collapsible section. Print shows everything.

Rule names come from `src/lib/rules.ts` (one per engine rule id). The component tests use
a fictional verdict made by the real engine: `python scripts/make_ui_fixture.py` regenerates
`src/test/fixtures/verdict-flag.json`.

## Run it during development

1. Start the API (it loads the OCR models in WSL): `scripts\serve.cmd` from the repo root.
2. In another terminal:

   ```
   cd frontend
   npm install
   npm run dev
   ```

3. Open <http://127.0.0.1:5174>. The dev server forwards `/jobs`, `/verify` and `/health`
   to the API on <http://127.0.0.1:8010>.

## Use it without the dev server

`npm run build` writes `frontend/dist`; the API server then serves the UI itself at
<http://127.0.0.1:8010/> (restart the API after building).

## How it talks to the server

* `POST /jobs` uploads the files (with upload progress) and gets a job id back at once.
* `GET /jobs/{id}` is polled every 2 s for the stage, pages read and time left, then the
  verdict. If the server can't be reached, polling retries with back-off; the case keeps
  running on the server.
* Only the job id is kept in the browser (sessionStorage), so a page refresh resumes
  following the case. The verdict, which holds personal data, is never stored in the
  browser; "Check another case" also deletes it from the server.

See `docs/api.md` for the endpoints.

## Checks

```
npm run build   # type-check + production build
npm test        # unit tests (vitest)
npm run lint    # oxlint
```

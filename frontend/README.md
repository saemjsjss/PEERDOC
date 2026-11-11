# HKLV Document Check - web UI

React 19 + Vite + Tailwind CSS + TypeScript. Upload a case (a ZIP, or PDFs and images), follow
the progress while the server reads it, then see the verdict.

## Run it during development

1. Start the API (it loads the OCR models in WSL): `scripts\serve.cmd` from the repo root.
2. In another terminal:

   ```
   cd frontend
   npm install
   npm run dev
   ```

3. Open <http://127.0.0.1:5173>. The dev server forwards `/jobs`, `/verify` and `/health`
   to the API on <http://127.0.0.1:8000>.

## Use it without the dev server

`npm run build` writes `frontend/dist`; the API server then serves the UI itself at
<http://127.0.0.1:8000/> (restart the API after building).

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

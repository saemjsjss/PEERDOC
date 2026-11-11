# Code review and upgrade suggestions — 2026-11-12

Scope: the whole repository at commit `5b55642`. That covers the Python backend (`hklv_api`, `hklv_pipeline`, `hklv_ocr`, `hklv_online`), extraction and rules (`hklv_extract`, `hklv_rules`), the React frontend, scripts, and tooling. No code was changed.

Current state:

| Check | Result |
|---|---|
| `pytest -q` | 849 passed, 2 skipped, 2 xfailed, 1 warning (Starlette/httpx deprecation) |
| `npm run build` | passes (254 kB JS, 79 kB gzip) |
| `vitest run` | 21 passed (2 test files) |
| `oxlint` | 0 findings |
| `npm outdated` | everything at latest except `@types/node` 24 → 26 (staying on 24 matches the local Node 24) |
| Backend runtime | fastapi 0.162.4, starlette 1.10.0, pydantic 2.14.3, uvicorn 0.54.0 |

Each item below was checked against the source. Items marked **(confirmed)** were also reproduced by running code in the venv. Items marked *unverified* are likely but not proven.

---

## Summary

The weakest area is **extraction**, not the rules engine. The rules engine handles uncertainty well: it FLAGs when data is missing or confidence is low. But it trusts whatever the extractor hands it, and several extractors match labels loosely. As a result, a correct, complete applicant file can get a **FAIL** verdict. Two of those cases are Blockers.

The second weak area is **resource limits on the server**. Upload bytes are capped, but nothing caps the work an upload causes: the number of pages, the pixels per page, or the run time. One crafted or simply unusual PDF can tie up the only GPU worker for hours, or crash the process and lose every stored verdict.

The frontend has no Blockers. Its gaps are test coverage and lint scope.

---

## 🔴 Blockers: wrong verdicts on valid files

### B1. A parent's birth certificate in the file fails BIRTH-03 and makes FatherRef/MotherRef uncertain (confirmed)

- **Where:** `src/hklv_rules/anchors.py:38-56` builds the parent anchors from *every* `BirthCertificate`. `rules/birth.py` runs BIRTH-01..04 on every certificate. `BirthCertificate.name` is extracted (`extractors.py:665`), but no rule reads it.
- **What happens:** applicants often include a parent's old-style birth certificate, and `group.py:8` already notes that this happens. Adding a father's certificate to an otherwise complete, passing case changes the verdict from PASS to **FAIL**: BIRTH-03 reports "birth year differs 1970 vs 2001". FatherRef also turns uncertain ("sources disagree"), which FLAGs NID-ASSIGN, REQ-08/09, FRC-03, BANK-01, TRADE-04 and CHAIN-02/03.
- **Fix:**
  1. Before building the anchors, match each birth certificate's `name` to StudentRef using the existing `assign_by_name`.
  2. Only the student's certificate should feed FatherRef/MotherRef and BIRTH-01..04.
  3. A certificate whose name matches a parent should be set aside, with a note in the result.
  4. A certificate whose name can't be read should FLAG.

### B2. Bank solvency letters and employment certificates that quote "NID No" are classified as NIDs (confirmed in source)

- **Where:** `src/hklv_extract/classify.py:61`. The `nid` signature includes the bare phrase `\bNID\s*(?:NO|NUMBER|CARD)\b`, and it is tested at line 207, *before* the statement, solvency and employment checks. The comment above that check says it sits last because FRCs, trade licences and TINs print NID numbers. Those three kinds are tested earlier, but solvency letters and employment letters are not.
- **What happens:** "SOLVENCY CERTIFICATE … Md Abdul Karim, NID No: 1234567890 …" becomes an NID. The result is a REQ-05/06 FAIL for the missing solvency or employment document, a spurious NID-01 FAIL (no translation), and an NID that can't be assigned to anyone.
- **Fix:** move the `nid` check below the statement, solvency and employment checks. Or drop bare "NID No" as a classifier and keep only the card titles ("NATIONAL ID CARD", জাতীয় পরিচয় পত্র). Add a test page for each case.

---

## 🟡 Major

### Extraction and rules

| # | Problem | Where | Failing input | Fix |
|---|---|---|---|---|
| M1 | The solvency letter's date takes the first line with "Date" in its label | `extractors.py:868` | "Account Opening Date: 01/02/2015" printed above "Date: 10/11/2026" gives letter date 2015, so BANK-03 FAILs | Use the letter-header pattern `frc()` already uses (`extractors.py:723`), and exclude Opening/Birth/Issue/Expiry |
| M2 | The "own name" label only excludes the exact spelling `Father's ` | `extractors.py:937` (TIN), `:681` (death), `:665` (birth), `:1003` (language test) | OCR drops the apostrophe: "Fathers Name: ABDUL RAHIM" is read as the taxpayer's name, so TIN-03 and CHAIN-01 FAIL | Define one shared `OWN_NAME_LABEL` that also rejects Fathers/Mothers/Husband/Spouse; add a test for each document kind |
| M3 | FRC relation matching is exact after removing non-letters (confirmed) | `rules/frc.py:176-188` | "Father (Late)" becomes `FATHERLATE`, "Self (Applicant)" becomes `SELFAPPLICANT`, and Bangla পিতা becomes empty; all three FAIL FRC-02/03 | Match on word tokens and ignore LATE/DECEASED/S; map পিতা/মাতা/নিজ; when a relation isn't recognised, FLAG instead of FAIL |
| M4 | The challan amount can come from the line under "Amount in words" (confirmed) | `extractors.py:944-961` | "Amount in words: Ten thousand / 5,000 / Total Amount: 10,000" gives 5,000, so TAX-04 FAILs | Use `Amount(?!\s*in\s*words)` with "Total Amount" checked first; FLAG when the labelled amounts disagree |

### Server resource limits

| # | Problem | Where | Fix |
|---|---|---|---|
| M5 | No cap on page count, and a running job can't be cancelled or timed out. A small PDF with thousands of pages holds the single GPU worker for hours, and everything else queues behind it | `jobs.py:169-170, 253-285`; `app.py:233` counts pages but only uses the count for the ETA | Reject uploads where `pages > MAX_PAGES` (the count already exists). Add a cancel flag that `read_files` checks between pages. Add an overall timeout |
| M6 | Pages render at a fixed 300 dpi with no pixel limit. A PDF page with a very large MediaBox renders to gigabytes; the OOM killer then ends uvicorn and every stored verdict is lost | `readers.py:91` (`page.render(scale=dpi / 72)`) | Read the page size first and clamp the scale to about 40 MP. Set `Image.MAX_IMAGE_PIXELS` explicitly and shrink large images |
| M7 | `POST /verify` skips the queue limit and the ETA. Any number of `/verify` calls can each write up to 400 MB to disk and wait on `case_lock`, while queued UI jobs show a wrong ETA | `app.py:271-298` vs `jobs.py:142-144` | Send `/verify` through `JobManager` (submit, then await completion), or count it against the same limit |
| M8 | A job is marked RUNNING before it gets the GPU lock. A job still waiting shows "Reading the documents", can't be cancelled (409), and gets an inflated ETA | `jobs.py:254` sets the status; the lock is only taken at `jobs.py:263` | Set status, stage and `started` inside the `async with self.case_lock` block |
| M9 | No protection against cross-site requests or DNS rebinding. The server is unauthenticated and protected only by binding to 127.0.0.1. A multipart POST is a CORS "simple" request, so any web page the operator visits can submit jobs, and through DNS rebinding can read the results of the jobs it submitted | `app.py` (no TrustedHost or Origin check) | Add `TrustedHostMiddleware(allowed_hosts=["127.0.0.1", "localhost"])`. Require a custom header (for example `X-HKLV: 1`) on POST and DELETE, which forces a CORS preflight. Optionally require a token generated by `serve.sh` |

### Frontend

| # | Problem | Fix |
|---|---|---|
| M10 | The riskiest code has no tests: `useJobPolling.ts`, `api.ts`, the screen transitions in `App.tsx`, `UploadScreen`, `ProgressScreen`. Only `lib/` and `ResultsScreen` are tested | Hook tests using fake timers and a stubbed `fetch` (stops on a terminal state, back-off, 404 calls `onGone`, unmount mid-request). App flow tests (upload → progress → results, cancel 409, resume). Tests for `errorFrom` |
| M11 | Lint is narrow and never runs on build. `.oxlintrc.json` has no `jsx-a11y` and no `react/exhaustive-deps` | Add both, plus a `check` script that runs lint, typecheck and tests |

---

## 🟢 Minor

**Extraction and rules**
- A currency prefix makes amounts unreadable. "Tk. 12,000" and "BDT 15,000.00" both return `None`, so TAX-02/03 FLAG (`extractors.py:947`). Lakh grouping (`1,00,000/-`) already works.
- MRZ birth-year pivot (`mrz.py:106-116`): the century is rolled back only when the year is in the future, not the full date. "261201" read today gives a future DOB of 2026-12-01.
- The TD3 passport number gets no O/0 look-alike repair, unlike TD1 (`mrz.py:131` vs `:174-178`). Impact is low, because no rule reads it.
- The Md/Mst policy is uneven (`names.py:17-22`). MD equals MOHAMMAD but not MOHAMMED or MUHAMMAD, and MST equals MOSAMMAT but not MOSAMMET. Either accept a set of spellings or record the narrow policy in the rulebook supplement.
- StudentRef compares names in order (`anchors.py:83`), but PASSPORT-01 ignores word order (`passport.py:139-150`). Share one `_same_name` function.
- If an extractor raises an exception, the whole case fails (`build.py:44-50`). Wrap each extractor call and emit an EXTRACTION-ERROR FLAG instead. No crashing input was found (*unverified*).
- TAX-04 returns FAIL on a website "NOT_FOUND" (`tax.py:162`). If OCR misreads the challan number, a valid challan FAILs. Make it FLAG, or get the FAIL approved in the supplement.
- A missing "same person" phrase is stored as a confident `False` at 0.8 confidence (`extractors.py:765`). That is safe only while the threshold stays above 0.8. Return an empty `Extracted` instead.

**Server**
- The online-check deadline doesn't limit slow responses. The 45 s total is checked only after `response.read(65536)` returns, DNS lookup has no timeout, and the checks run inside `case_lock`, so a slow government site holds the GPU idle (`checks.py:81-87`, `pipeline.py:141`). Use `read1()` or httpx with a total timeout, cap the number of checks, and run them outside the lock. *Partly unverified.*
- `HTTPError` responses are never closed (`checks.py:94-95`). Call `e.close()`.
- Upload chunk writes and `shutil.move` run on the event loop (`uploads.py:181-195`), so a 150 MB upload stalls polling for every other client. Use `asyncio.to_thread`.
- The startup sweep deletes `hklv-case-*` folders that another instance on a different port is still using (`app.py:53-61`). Use a per-instance subfolder or a PID lock.
- After a restart, verdicts disappear but the 404 message says they are "kept for one hour". Add a server instance id so the UI can say "server restarted".

**Frontend**
- Polling retries forever on a persistent 5xx (`useJobPolling.ts:44-53`). After N failures, show "Keep waiting / Start again".
- A `done` job without a `result` stays on the 100% progress screen forever (`App.tsx:216-241`). Treat it as `failed`.
- "Check another case" awaits the DELETE with no timeout and no busy state (`App.tsx:194-199`). Reset the UI first and send the delete in the background.
- The client doesn't check the 200-file limit, so selecting 250 files uploads everything before getting a 413. Add `MAX_FILES` to `lib/files.ts`.
- Accessibility:
  - The `aria-live` region announces every page change for about 8 minutes (`ProgressScreen.tsx:79-82`).
  - Focus is lost on the Upload → Progress and Results → Upload transitions.
  - The ▾/▸ glyphs are read aloud.
- React keys can collide in the ignored-file lists (`key={f.name}`).
- Set TypeScript `strict`, `noUncheckedIndexedAccess` and `exactOptionalPropertyTypes` explicitly. Right now strictness depends on the TS 7 default.

---

## Upgrade suggestions (tooling and dependencies)

1. **Pin the Python runtime.** `setup_ocr.sh:107` runs `pip install -U`, so each install gets whatever is newest. The lock file `requirements-ocr.lock.txt` is written afterwards and never installed from. Install with `pip install -r requirements-ocr.lock.txt` and add upper bounds in `pyproject.toml` (`fastapi<0.163`, `starlette<2`). The code relies on Starlette 1.x behaviour, for example the request-body middleware at `app.py:129-138`.
2. **Add Python lint and type checks.** Add `[tool.ruff]` with the `B`, `BLE`, `S` (security) and `ASYNC` rules, and `[tool.mypy]` or pyright. The `# noqa: BLE001` comments show the intent is already there.
3. **Add CI.** There is no `.github/` folder. Add one workflow that runs `pytest`, `ruff`, `mypy`, `npm run build`, `vitest` and `oxlint --deny-warnings`. The OCR tests that need the GPU can be skipped there.
4. **Small Python modernisations:**
   - `Annotated[list[UploadFile], File(...)]` in the route signatures (`app.py:224-227, 273-276`)
   - `enum.StrEnum` for `JobStatus` and `Stage`
   - remove `response_model=` where the return annotation already says the same
   - fix the stale `1.0.0` version in `docs/api.md:101` (the code says `1.1.0`)
5. **Split `extractors.py` (1,145 lines).** Suggested split:
   - `_tables.py` for the grid and column helpers
   - `identity.py` for passport, NID and birth
   - `financial.py`
   - `academic.py`

   Remove the duplicates along the way: `_digits` and `digits`, the QR lookup, the fiscal-year regex, and the copy-pasted "own name" lookbehind behind M2. Move the private `_PARENTS` and `_Income` out of `financial_chain.py`, since `tin.py` imports them.
6. **Make `.gitignore` safe for personal data.** Real applicant folders (`SAMPLE DOC 2/`, `4/`) are kept out of git today only because their files happen to be PDF or JPG. A `.tif`, `.webp`, `.zip`, `.docx` or `.txt` scan dropped into those folders would be committable. List the folders explicitly, or move all real data under one ignored `private/` folder and add `*.tif`, `*.tiff`, `*.webp`, `*.heic` and `*.zip`.
7. **Frontend:** stay on `@types/node` 24 to match Node 24. Everything else is current.

---

## Missing tests (each finding above should get a regression test)

- A parent's birth certificate included in a case (B1)
- Solvency and employment letters that quote "NID No" (B2)
- A solvency letter with an "Opening Date" line (M1)
- "Fathers Name" without an apostrophe on TIN, death, birth and language-test documents (M2)
- FRC relation variants: "Father (Late)", "Self (Applicant)", Bangla (M3)
- A challan with "Amount in words" (M4)
- Amounts with a Tk/BDT prefix; the MRZ century pivot within the current year; an extractor raising an exception
- An upload over the page limit and a page over the pixel limit (M5, M6), once those limits exist

## Suggested order

1. B1, B2, then M1–M4. Each is a small, local change in extraction or rules that stops valid files from FAILing. Write the failing test first.
2. M5, M6, M8, then M7. These protect the single GPU worker and the in-memory verdicts.
3. M9: two middleware lines plus a header added in `api.ts`.
4. Tooling: pin dependencies, add ruff and mypy, add CI, fix `.gitignore`.
5. Frontend tests and lint, then the minor items.

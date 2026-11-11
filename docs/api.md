# HKLV API

A FastAPI backend that runs the whole pipeline on one student's uploaded documents and
returns the verdict as JSON. It runs inside the WSL OCR environment, because the OCR models
need the GPU there.

## Start

The server also serves the web UI at <http://127.0.0.1:8000/> once it has been built
(`npm --prefix frontend run build`; see `frontend/README.md`).

From Windows (cmd or PowerShell):

```
scripts\serve.cmd
```

or inside WSL:

```
bash /mnt/c/dcSS/scripts/wsl/serve.sh
```

The OCR models load once at startup (about 20 s). Interactive docs are at
<http://127.0.0.1:8000/docs>. The server listens on **127.0.0.1 only**: it is reachable from
this Windows machine (WSL forwards localhost) but not from the network. `HKLV_PORT` changes
the port. One worker: the GPU is a single shared resource, and pages from concurrent
requests take turns on it.

## Jobs: `POST /jobs`, `GET /jobs/{id}`, `DELETE /jobs/{id}` (what the web UI uses)

A full case takes about 8½ minutes, too long to hold one request open. So:

1. `POST /jobs` takes the same form fields as `/verify` (below), checks and stores the
   upload, and answers **202** at once with a job: `job_id`, `status` `queued`, `pages_total`,
   `files` (accepted / ignored), `eta_seconds`.
2. `GET /jobs/{job_id}` every couple of seconds:

   | Field | Meaning |
   |---|---|
   | `status` | `queued`, `running`, `done`, `failed` |
   | `stage` / `message` | `waiting` (behind other cases), `reading` (OCR), `checking` (online checks and rules), `finished` |
   | `pages_done` / `pages_total` | pages read so far |
   | `progress` | 0..1 for a progress bar |
   | `eta_seconds` | estimated seconds until the verdict (learned from this server's own speed) |
   | `queue_position` | cases ahead of this one while queued |
   | `result` | the same verdict JSON as `/verify`, once `status` is `done` |
   | `error` | the error type, if `status` is `failed` |

3. `DELETE /jobs/{job_id}` cancels a waiting job or forgets a finished one (204). A job whose
   pages are being read can't be stopped half-way (409).

One worker reads one case at a time (the GPU is shared); other cases wait in the queue (at
most 20, else 503). A job's uploaded files are deleted the moment it finishes, fails or is
cancelled. Verdicts are kept in memory only, for one hour after the job ends (then 404), and
are lost if the server restarts. Job ids are long random tokens.

## `POST /verify`

`multipart/form-data`:

| Field | Required | Meaning |
|---|---|---|
| `files` | yes, one or more | PDFs and images (`.pdf .jpg .jpeg .png .bmp .tif .tiff .webp`) and/or `.zip` files containing them. ZIPs are unpacked flat; other files, ZIPs inside ZIPs and encrypted entries are skipped and listed under `files.ignored`. |
| `case_id` | no | Your reference for the case (default `upload`). |
| `evaluation_date` | no | `YYYY-MM-DD`; the "current date" every date rule uses (default: today). |
| `online` | no | `true` (default) checks e-Apostilles on apostille.mygov.bd and automated challans on www.achallan.gov.bd; `false` skips that (ACAD-01 / TAX-04 then FLAG). |

Example:

```
curl -F "files=@student.zip" -F case_id=2026-0417 -F evaluation_date=2026-11-11 http://127.0.0.1:8000/verify
curl -F "files=@passport.pdf" -F "files=@photo.jpg" -F "files=@nid.pdf" http://127.0.0.1:8000/verify
```

Response (200):

| Field | Meaning |
|---|---|
| `outcome` | Final overall verdict: `PASS`, `FLAG` (needs manual review) or `FAIL` |
| `summary` | One line, e.g. `FLAG: needs manual review; 2 rule(s) flagged (BIRTH-02, BIRTH-04)` |
| `counts` | `{passed, flagged, failed}` |
| `failures`, `flags` | The FAIL and FLAG rule results: `rule_id`, `outcome`, `reason`, `evidence` (document, field, value read, page, and the OCR `confidence` 0..1 behind the value; below 0.90 a reading is not trusted and the rule FLAGs) |
| `results` | Every rule result, PASS included |
| `documents` | The extracted documents (passport, NIDs, ...) with every field's value, OCR confidence and page |
| `pages` | How each uploaded page was classified (`kind`, `doc_id`, reason, source file and page) |
| `online` | Each e-Apostille / challan check: `VERIFIED`, `NOT_FOUND`, `UNAVAILABLE`, or `null` if not checked |
| `files` | `accepted` file names; `ignored` ones with the reason (unsupported type, ZIP inside a ZIP, encrypted, corrupt, or a file the OCR reader can't open, e.g. an empty PDF); `ignored_more` counts any beyond the first 50 |
| `timings` | Seconds spent in OCR, extraction, online checks, rules |

The response contains the student's personal data; treat it accordingly.

Errors: `400` no readable PDF/image in the upload, or an unreadable ZIP (the body lists what
was ignored); `413` too large (150 MB uploaded, counted on the bytes actually received, so
chunked uploads are capped too; 400 MB unpacked), too many files (200) or ZIP entries (2000); `422`
invalid form values (e.g. a bad date); `500` the pipeline failed (only the error type is
reported, never document content); `503` OCR models not loaded.

## `GET /health`

`{"status": "ok", "version": "1.0.0", "models_loaded": true}`

## Privacy

* Uploads are written to a temporary folder per request inside a private, owner-only work
  folder (`~/hklv-ocr/work` in WSL) and deleted when the response has been built, whether
  the run succeeded or failed. Folders left behind by a killed server are deleted at the next
  start. Nothing is stored on the server.
* File names are kept only to order pages and to point at them in the response; documents
  are classified by their content.
* Logs contain request lines and error types, never document content or file names.
* Uploaded file names are cleaned (folders dropped, at most 150 bytes); a ZIP entry such as
  `../../x.pdf` is saved as `x.pdf` inside the request's folder.

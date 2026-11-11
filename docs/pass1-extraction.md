# Pass 1: from scans to a `CaseFile`

## Running the whole pipeline (folder in, verdict out)

```powershell
scripts\run_case.cmd "C:\dcSS\SAMPLE DOC" --date 2026-11-11
```

`run_case.cmd` starts `run_case.ps1` (bypassing the PowerShell script policy for that run),
which hands over to WSL (`scripts/wsl/run_case.sh`), where `scripts/run_case.py` runs
OCR → extraction → rules (`hklv_pipeline.run_case`) and prints the page map, the final
verdict and every FAIL and FLAG reason.

* Outputs go to `ocr_output/<folder name>/` (git-ignored): `reading.json` (saved the moment
  OCR finishes), `case.json`, `verdict.json`. Old results there are removed first.
* `--reading <reading.json>` re-judges a saved reading without OCR (seconds; works from the
  Windows venv too). `--case-id`, `--out`, `--no-pages` are optional.
* Online checks run by default after extraction: each e-Apostille's application number is
  looked up on apostille.mygov.bd and each automated challan on the Finance Division's
  A-challan system (see `docs/rulebook-supplement-draft.md`, "Online checks"). `--offline`
  turns them off; ACAD-01 / TAX-04 then FLAG as "not verified online".
* Exit code: 0 PASS, 1 FLAG, 2 FAIL, 3 error (bad arguments and crashes included, so a
  wrapper never mistakes a crash for a verdict).
* Relative and Windows paths work from wherever the command is run.

First automated verdict on the sample set (2026-11-11): **FLAG**, 21 checks passed, the only
flag being ENGINE-COVERAGE (rules not yet written). A second full read gave the same 182
extracted values and confidences as the first. OCR of the 34 pages now takes about 7 minutes
(see "GPU memory and speed" below); it took 40 before.

Pass 1 turns the uploaded files into the typed documents the rules engine checks. It runs
in two halves so that the GPU part stays small and everything else is testable anywhere.

```
uploads ──► readers (GPU, WSL)  ──► reading.json ──► extraction (pure Python) ──► CaseFile ──► rules
            src/hklv_ocr/                            src/hklv_extract/
```

## 1. Readers (`src/hklv_ocr/readers.py`)

Every page is rendered at 300 dpi and read by three independent readers:

| Reader | Gives | Why |
|---|---|---|
| PP-OCRv6 (PaddleOCR 3.7 default det + rec) | text lines **with a confidence score each**, boxes | The main source of field text. Reads all MRZ lines at 300 dpi. |
| PaddleOCR-VL-1.6 (on a half-size image) | layout blocks: text, tables (HTML), `seal`, images | Second opinion on the text; table structure; seal detection. No scores. |
| ZXing-C++ | QR codes and barcodes, decoded | TIN QR (taxpayer name and TIN), e-Apostille URLs, passport barcode. |

`PageReader` is async: model calls run in a worker thread behind one GPU lock, so the
future FastAPI service can await it. The raw result of all three readers is saved as
`reading.json` (git-ignored, it holds real personal data) and is the only input to
extraction.

Run on a folder:

```powershell
wsl -d Ubuntu -- bash -c "cd ~/hklv-ocr && LD_LIBRARY_PATH=/usr/lib/wsl/lib ~/hklv-ocr/.venv/bin/python /mnt/c/dcSS/scripts/wsl/read_case.py '/mnt/c/dcSS/SAMPLE DOC' /mnt/c/dcSS/ocr_output/sample_doc/reading.json"
```

Runtime settings: PaddleOCR-VL gets a half-size image (`VL_SCALE`, ~150 dpi; at 300 dpi each
block costs ~4x the vision tokens) and at most `VL_MAX_NEW_TOKENS` per block, because it
sometimes loops on repeated text.

## 2. Extraction (`src/hklv_extract/`)

| Step | Module | What it does |
|---|---|---|
| Classify each page | `classify.py` | Rulebook 1.1 signatures, most specific first. File names are never used. Unmatched pages are ignored (IGNORE-01). |
| Group pages into documents | `group.py` | Consecutive pages of one kind form one document (NID card + its translation). A card number (valid MRZ, else printed "NID No") differing in 4+ digits starts a new one; 1-3 digits is a typo on the same card, which NID-03 must see. Apostilles, certificates and transcripts are one page each. |
| Extract fields | `extractors.py` | One function per document type, returning the rules engine's Pydantic model. |
| Assemble | `build.py` | `build_case(reading, case_id, evaluation_date) -> (CaseFile, ExtractionReport)` |

`scripts/extract_case.py reading.json --date YYYY-MM-DD --out case.json` runs extraction and
the rules engine and prints the page map and verdict.

### Classification order (why it matters)

The same words recur across document types, so the order of checks is part of the rules:

1. Photo (image file, almost no text), passport (passport MRZ), e-Apostille.
2. **Affidavit** ("Affidavit", "same person"): it lists other documents by name ("Birth
   Certificate", "Mother's NID"). "Notary Public" alone is not a signature: every notarised
   translation has it.
3. NID with an ID-card MRZ.
4. **Trade License** (also its verification QR, ".../verify/trade..."): it has the owner's
   birth-registration field.
5. **Death** before birth, but only on "Death Registration Number" / "Death Certificate" /
   "Date of Death": every BDRIS birth certificate is issued by the "Registrar of Birth and
   Death".
6. Birth, FRC, tax challan / acknowledgement / certificate, **TIN before "Return of Income"**
   (a TIN certificate tells the taxpayer to file one).
7. NID without MRZ ("National ID Card", "NID No"), last of the identity checks: FRCs, trade
   licences and TINs all print NID numbers.
8. Bank statement, solvency ("To Whom It May Concern" only together with bank + account
   words), employment, academic, IELTS/TOPIK.

Academic certificates and transcripts count only inside an apostille block (section 1.1); a
university's recommendation letter is ignored.

### Field-finding conventions

* Label then value on the same line, on the same row to the right (two-column forms;
  one-digit-per-box numbers are joined), or on the next line. A column far to the right
  is a different field.
* Strict value patterns: a label can match the wrong line (the notary's own "License No."
  on a trade licence translation), so the value must look like the field (6+ digits).
* If PP-OCRv6 has no value, PaddleOCR-VL's text is searched the same way; a value only it
  saw scores `VL_ONLY` (0.60, so FLAG).
* Academic level = the highest level the page names (a bachelor transcript also says
  "HSC or equivalent").
* Dates are day-first; two different dates in one field are not chosen between. Board
  certificates spell the date of birth out ("Fifth August Two Thousand"); that is parsed
  only if it parses completely, and checked against the second reader.

## 3. Where confidence comes from (`confidence.py`, `mrz.py`)

The rules engine FLAGs any value below the confidence threshold (0.90 for now), so every
extracted value carries a score built from independent evidence, never from one reader's
say-so:

| Evidence | Confidence |
|---|---|
| MRZ field whose check digit (and the composite check) validates | 0.99 |
| MRZ field whose check digit fails | 0.40 |
| PP-OCRv6 value also present in PaddleOCR-VL's text of the page | line score, capped at 0.99 |
| PaddleOCR-VL has a near-miss of the value (1 letter per 5 different) | **0.50**: the readers disagree, so FLAG |
| PaddleOCR-VL has nothing like it | line score × 0.92 (passes alone only if the line score is ≥ ~0.98) |
| Printed name matches the MRZ name (word order ignored) | 0.99 |
| Seal block whose own ring text (PaddleOCR-VL seal recognition) has a word starting "NOTAR"/"ADVOCAT" | 0.95 (seal shape + the notary's name on it) |
| Seal block whose ring text says something else (Union Parishad, university, consular seal, emblem) | the layout detector's own score, never boosted |
| Seal block with no readable text, within ~3.4 cm of "Notary Public"/"Advocate" text | 0.95 |
| Any other seal block | the layout detector's own score (seen: 0.48–0.94), so usually FLAG |
| No seal block found | `stamp_present = False` at 0.50, so FLAG, not FAIL: the layout model misses some embossed seals |

MRZ text is repaired only where a check digit guards the repair (O→0, I→1 ... in numeric
fields); names are never corrected. A zone whose line has an extra or missing real
character is rejected, not re-aligned.

These numbers are placeholders until calibrated on more real cases.

## 4. Result on the real sample set (2026-11-11)

15 files, 34 pages (personal data stays in the git-ignored `ocr_output/sample_doc/`):

* **All 34 pages classified correctly**: 28 pages into 23 documents (an NID card and its
  translation, or the trade licence's English translation and Bangla original, form one
  document), and 6 ignored as intended (CV, SOP, CEFR, recommendation letters, including a
  university letter that looks like a certificate but sits outside an apostille block).
* All MRZ zones validate (passport and three NIDs); every name the rules compare
  (anchors, NID holders, FRC rows, affidavit, TIN, trade licence owner, bank holder) is
  read correctly at 0.97-0.99, including the ones PaddleOCR-VL alone got wrong.
* ZXing decodes the TIN QR (name and TIN match the print) and all five apostille URLs.
* Verdict: every rule implemented so far passes; the only FLAG is ENGINE-COVERAGE
  (rules still to write).
* Still weak, honestly flagged: the birth registration number (one digit per box,
  PP-OCRv6 misses some boxes, so the value comes from PaddleOCR-VL alone at 0.60), two
  NID stamps (seal away from the notary text, 0.82-0.89), bank statement holder (0.88).

### GPU memory and speed (measured 2026-11-11, RTX 5060 8 GB)

Peak GPU memory per reader stage, measured page by page:

| Stage | Time per page | Paddle GPU peak |
|---|---|---|
| Loaded models, idle | | 3.2-3.8 GB |
| PP-OCRv6 text lines (full 300-dpi page) | 2-4 s | **7.6-8.7 GB** (detection on ~2500x3500 px) |
| PaddleOCR-VL layout + text | 7-43 s | 3.7-5.3 GB |
| ZXing | 0.1 s | none |

Paddle's allocator keeps what it reserves. Text detection reserves the whole card for a few
seconds, and PaddleOCR-VL, the slow stage, then ran with the card still full, so it spilled
into shared system memory. Clearing the cache only once per page was not enough: the
passport page took 55 s that way, against 16 s with the cache also cleared **between** the
two readers.

The reader now renders one page at a time and calls `paddle.device.cuda.empty_cache()`
between the readers and after every page. Full sample set, same machine:

| | OCR time | Slowest page | Output |
|---|---|---|---|
| Before | 2,430 s (40.5 min) | ~150 s | |
| After | **433 s (7.2 min)** | 49 s | raw text identical on all 34 pages; all 182 extracted values identical |

Every run prints time and memory per page and saves them to `ocr_stats.json`.
`HKLV_KEEP_GPU_CACHE=1` restores the old behaviour, for A/B timing only.

Still open: text detection itself peaks at the card's limit. Capping its input size
(`text_det_limit_type="max"`) would remove that spike, but it changes what is detected and
needs its own accuracy check, especially on MRZ lines.

## 5. Known gaps

* Bangla text: neither reader reads it reliably. English translations are the source of
  truth; Bangla only decides the document's language.
* IELTS/TOPIK pages are classified but not extracted (no LANG rules yet).
* Cross-document agreement (the same name on many documents) is not used to raise or lower
  confidence yet.

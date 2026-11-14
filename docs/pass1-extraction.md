# Pass 1: from scans to a `CaseFile`

## Running the whole pipeline (folder in, verdict out)

For the HTTP API (`POST /verify` with files or a ZIP), see [api.md](api.md).

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
   birth-registration field. The English title counts only on a line of at most 8 words
   (RULES-v13): a personal statement that mentions "a valid trade license" is not one.
5. **Death** before birth, but only on "Death Registration Number" / "Death Certificate" /
   "Date of Death": every BDRIS birth certificate is issued by the "Registrar of Birth and
   Death".
6. **FRC before birth** (an FRC table lists the members' birth registration numbers), then birth, tax challan / acknowledgement / certificate, **TIN before "Return of Income"**
   (a TIN certificate tells the taxpayer to file one). Birth: "Birth Registration
   Number/No", BDRIS or the Bangla title. Older City Corporation certificates (BDR Form-3)
   are recognised **after the FRC check** by the birth registrar office ("Office of the
   Birth and Death Registrar", "BDR Form") + "Date of Birth" + two fields of the birth
   register, at least one a register entry ("Register No", "Date of Registration",
   "Order of Child"); the other may be the certificate's own 16-17 digit number after
   "BR Number"/"BRN", counted only with no "NID" beside the label (combined "NID/BRN",
   "BRN/NID", "NID or BRN" fields are on citizenship certificates and cover letters).
   "Place of Birth" does not count (letters and forms print it). The decorative title is
   not used (OCR garbles it, and cover letters, checklists and FRC tables name it too).
   Each register entry counts only with its value (an application form's blank
   office-use "Register No.:" does not), a parent's "Father's BRN" is not the page's own,
   and pages that call themselves something else (citizenship, character, warish/heir,
   succession certificates, applications) are excluded: the Union Parishad chairman is
   also the registrar and signs those too. Such a page joins a neighbouring birth
   certificate page only when both show the same own registration number (its
   translation); otherwise it is a document of its own (it may be a parent's). Known,
   unchanged from before: every birth certificate in a case is checked against the
   student's passport, so a parent's own certificate in the upload FAILs BIRTH-03 (as a
   parent's BDRIS certificate always did).
7. NID without MRZ ("National ID Card"), last of the identity checks: FRCs, trade
   licences and TINs all print NID numbers.
8. Bank statement, solvency ("To Whom It May Concern" only together with bank + account
   words), employment, then a page that only quotes an "NID No" (an NID only now: bank and
   employer letters quote one), academic, IELTS/TOPIK.

Academic certificates and transcripts count only inside an apostille block (section 1.1); a
university's recommendation letter is ignored.

### Field-finding conventions

**Fallback lookups are evidence, never confident (at most 0.60, FLAG).** Some layouts are
read by lookups added after the label lookups below: a bank account number from a
details-table column, a birth registration number after "BR Number", a date of birth
written in boxes or in words. Each was shown, in twelve rounds of adversarial review,
to have layouts where it reads another field confidently (a second account, a parent's
number, a registration date), and a confident wrong value FAILs a correct case where a
missing one only FLAGs. So the value is shown to the reviewer and the rule FLAGs. These
lookups run only where the label lookups find nothing; whatever those found before, they
still find, exactly as before. Raising any of them above 0.60 should wait for evidence
from real readings.

* Label then value on the same line, on the same row to the right (two-column forms;
  one-digit-per-box numbers are joined), or on the next line. A column far to the right
  is a different field.
* Strict value patterns: a label can match the wrong line (the notary's own "License No."
  on a trade licence translation), so the value must look like the field (6+ digits).
* If PP-OCRv6 has no value, PaddleOCR-VL's text is searched the same way; a value only it
  saw scores `VL_ONLY` (0.60, so FLAG).
* Bank account number: the label lookup above, unchanged, except that a date
  ("05-10-2026") is never an account number. Known and unchanged (xfail tests): after a
  table header row read as one line, or a label alone above a row, the label lookup takes
  the first number-shaped cell on the next line, which can be another column's (a
  Customer ID) or a serial number joined to the account ("1 0123456789012").
* Only when the label lookup finds nothing, bank account numbers can also come from a
  details table whose column header is
  "Account Number" with the number further down the column (the label lookup only sees
  the neighbouring headers there). PaddleOCR-VL's table is expanded into a grid with
  `rowspan`/`colspan` honoured; PP-OCRv6 counts only with the line right under the header,
  wholly inside the column, not followed by a wrapped piece, and no other number in the
  column. Several accounts, a masked number or anything unclear give no value (FLAG).
  A value shaped "1 0123456789012" is a row's serial number read together with the account
  number (by one reader or both alike) and is never taken.
  Never from a transaction / transfer table (Debit, Credit, Particulars ... in the header
  row: its account column is the other party's), and never when the holder's own
  "Account No:" field is printed but masked (anywhere: "XXXXXXXX7001", "1501XXXXX7001")
  or unreadable. Not confident when the letter's own text names an account with a
  different 10+ digit number ("Savings A/C # 1501..."): the table may list another of the
  holder's accounts (an FDR).
* "Account holder" in the solvency letter's own sentence keeps "Md"/"Mst": under the name
  policy "MD X" and "X" are different names. Only Mr/Mrs/Ms are dropped.
* Academic level = the highest level the page names (a bachelor transcript also says
  "HSC or equivalent").
* Birth registration number: the lookup above first, unchanged; only if it finds nothing,
  "BR Number", one digit per box allowed, exactly 16-17 digits, never cut out of a longer
  run; only the first such label on the page (the child's, printed above the parents'),
  only if nothing on its row names a parent (any apostrophe), from PP-OCRv6's lines only,
  and never moving on to a later label. The birth certificate's date of birth may be
  written in boxes ("08 05 2006"): read only there, as exactly eight digits on the "Date
  of Birth" line or its row (never the lines below: a registration date; elsewhere an
  8-digit ID could form a date); its "In Word: 8th
  May, 2006" (or "Fifth August Two Thousand One") line is the fallback when its boxes
  don't read; only that line (or, for a label in its own box, the nearest box on its row),
  cut at the next field's label, and only if it names the month; never the registration or
  issue date near it. Hyphenated days ("Twenty-Fifth") are read as one number. A date of
  birth from the In Word line alone is never confident (at most 0.60, FLAG): wrapped or
  misspelt words still parse to a valid, different date ("Two Thousand / Six" -> 2000).
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
| Account number from a table column: PP-OCRv6's line under the header and PaddleOCR-VL's cell under the same header give exactly the same digits (whole numbers, never one inside a longer one) | 0.60, FLAG (fallback lookup: evidence only, see above) |
| Account number from a table column: the readers' digits differ, or VL's column is unclear (several numbers, a masked one, a row that doesn't line up with its header) | **0.50**, FLAG |
| Account number from only one reader's column (PP-OCRv6's line under the header, or PaddleOCR-VL's cell) | 0.60, FLAG: PP-OCRv6's column geometry is fooled by joined or wrapped lines and VL's cells shift when it merges or drops one, so neither is confident alone |
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

## 5. OCR misreads the rules allow for

Moved here from the rulebook (RULES-v9), which keeps only the policy each one serves.

* Translation agency letterhead: the agency's own "Trade Licence No." on every translated
  page, even with an OCR slip in the number (e.g. "D60631"), does not make the page a
  trade licence (Section 1.1).
* Notary seal ring text: "NOTARY PULIC" counts as a word starting "NOTAR"; "REG NO TAREK"
  does not (Section 0, Notarised).
* The notary's red foil seal is found by colour (`hklv_ocr/red_seal.py`), not by text.
* MRZ names: digits are read as their look-alike letters (0->O, 1->I, 2->Z, 5->S, 6->G,
  8->B), since names hold no digits (2.1, PASSPORT-01).
* Old BDR Form-3 birth certificates: the filled square between month and year
  (`25 | 02 | ■ | 2002`) is skipped when the date is read (BIRTH-03).
* FRC tables: when the layout reader returns only part of the table, the dropped FATHER /
  MOTHER cells are unreadable rows, so FRC-03 FLAGs instead of FAILing.
* Challans: the amount is read from "Total Amount", never from the line under "Amount in
  words" (TAX-04).

## 6. Known gaps

* Bangla text: neither reader reads it reliably. English translations are the source of
  truth; Bangla only decides the document's language.
* Cross-document agreement (the same name on many documents) is not used to raise or lower
  confidence yet.

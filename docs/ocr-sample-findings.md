# PaddleOCR-VL-1.6 on the real sample set: what it gets right and wrong

Run of 2026-11-11: 15 files, 36 pages, no crashes, about 7.5 minutes on the RTX 5060.
Seven independent reviewers compared the OCR output against the original scans, field by
field, for the 10 documents the rulebook uses. This summary has no personal data; the
detailed review (with real values) is in `ocr_output/sample_doc/accuracy_review.json`,
which git ignores.

**307 fields checked: 200 exact, 107 not exact.**

| Problem | Count | Impact on the rules |
|---|---|---|
| Notary stamp / seal not identifiable as a stamp | 29 | NID-02, BIRTH-02, FRC-05, TRADE-02 can't confirm the stamp |
| Names, numbers or dates misread | 27 | False name mismatches, wrong numbers |
| Passport / NID MRZ cut off after line 1 | 20 | StudentRef (MRZ vs print) can't be checked |
| Fields missed entirely | 14 | e.g. the Trade License owner name on the translation |
| QR codes / e-Apostille QR not decoded | 10 | Expected: QR needs ZXing, not OCR |
| Bangla text replaced by other scripts | 7 | Bangla originals are unusable as a source |

## What works

* **Every page's document type is recognisable from its content.** Reviewers could tell all
  36 pages apart from the OCR text alone, so content-based classification (section 1.1) is viable.
* English pages are mostly accurate: NID translations, bank documents, the affidavit's
  "same person" sentence, apostille text, and notary text are usually read word for word.
* Speed: a few seconds per page, up to ~90 s for some multi-page files.

## What breaks the rules if used as-is

1. **Single-letter name errors with no warning.** A parent's name on the birth certificate
   came out one letter wrong, which would turn the mother anchor and every document that
   uses it into mismatches. Similar errors on an NID card, two academic documents and a
   handwritten affidavit name. PaddleOCR-VL gives no confidence score, so nothing marks them.
2. **MRZ lines are truncated or dropped** on the passport and all three NIDs (line 2 and 3
   missing, `I` read as `1`). MRZ is the most checkable data on those documents.
3. **Bangla text turns into Telugu, Tamil, Tibetan or Devanagari gibberish.** The Bangla
   Trade License original and the Bangla sides of NID cards are unusable.
4. **The Markdown output drops header/footer blocks** (notary attestations, letterheads).
   They are only in the JSON, so extraction must read the JSON blocks, not the Markdown.
5. **Hallucinated text** appears in apostille footers and as long repeated runs after the
   real content on one page.
6. **Stamps are image blocks, not text.** The layout model sometimes labels a block `seal`,
   but often only `image`, and it misses some red embossed seals entirely.

## What Pass 1 needs before its output can feed the rules engine

* **A confidence signal per field**, for example:
  - a second, independent reader (classic PP-OCRv5 returns a per-line score) and agreement checks;
  - MRZ check digits, read with a dedicated MRZ reader on the cropped MRZ zone;
  - cross-document agreement (the same name on 4+ documents).
* **ZXing** for every QR code and barcode (TIN, e-Apostille, NID, passport).
* **English translations as the source of truth**; Bangla text only to detect language.
* **Stamp detection** from the layout model's `seal` blocks plus notary text, with FLAG when unsure.

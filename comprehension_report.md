# Stage 6 — Comprehension Test: rules/RULES-v8.md

Target: `C:\dcSS\rules\RULES-v8.md`, the whole file (the reviewer counted 336 lines).
Reviewer: `egm-comprehension`, in a fresh context. It read only the target file, with no background.

## What this proposes

Version 8 of the full rulebook for the "HKLV" document-checking engine. It makes one change from v7, to EMP-05. An employment or experience letter reliably in the student's own name now counts as the student's CV material rather than a sponsor's income document. It is skipped like an unrecognised page: no EMP checks, it does not count towards REQ-06, and it is left out of the financial chain. A student name read with low confidence is still checked and gets FLAG. This replaces the v7 outcome "Student -> FAIL".

The file also sets a versioning policy. Rules are never edited in place. Every change, including additions, produces a new complete file (RULES-v9.md and so on) that lists its changes at the top.

## How the existing system works, per this document

The engine takes the files submitted for one student, who appears to be Bangladeshi, and works in passes.

1. **Pass 1** OCRs every page and classifies it by keyword signature: passport, birth certificate, NID, family certificate, bank, trade licence or employment letter, TIN, academic, tax, language test, death certificate or affidavit. Pages that match no signature are dropped.
2. **Pass 2** builds identity anchors: the student's name from the passport, and the parents' names from the student's birth certificate. Each NID is then assigned to the student, the father or the mother by name.
3. **The checks** come next: required documents, per-document rules and cross-checks. The main cross-check is the "financial chain": the TIN, the income document and the bank solvency must all belong to the same parent.
4. **The verdict** is the worst result of any rule. Any FAIL makes the case FAIL, otherwise any FLAG makes it FLAG, otherwise it PASSes. An empty result list or unimplemented rules force FLAG.

A separate component (`hklv_online`) checks e-Apostilles and tax challans against two government websites before the rules run. OCR confidence below 0.90 normally gives FLAG rather than a guess.

## Findings

No section was impossible to restate, so there are no Blockers.

### Major

1. **The purpose is never stated** (lines 1-5, 21).
   - Missing: what HKLV stands for, who submits the documents, and what the application is for (which country, admission or visa).
   - "Case" and "the owner" are never defined.
   - Without the purpose, the reader cannot judge the intent of rules such as REQ-06 (parental income) or the FAIL on a sibling's NID.
2. **"3-pass architecture", but Pass 3 is never named** (line 21).
   - It is unclear whether Sections 3-6 together are Pass 3.
   - Section 7 puts the online checks "between extraction and the rules", but "extraction" is not tied to any pass.
3. **Page classification has gaps** (Section 1, lines 59-90).
   - There is no precedence order for a page that matches several signatures. "To Whom It May Concern" also appears on employer letters.
   - Line 69 hints at an order but never gives it.
   - The Affidavit signature (line 90) has no AND/OR. Read as OR, every notarised page would be an affidavit.
   - The document never says how pages are grouped into one document, or how a translation page is linked to its original. NID-01, NID-03, BIRTH-01 and the Section 0 translation rules all depend on that link.
4. **Academic documents** (line 83, ACAD-02/03/06).
   - "Academic block" is not defined.
   - The document never says how a certificate is told apart from a transcript, or how a document's level is found. ACAD-02 pairs documents by exactly those two things.
   - SSC, HSC, Alim, Dakhil and Diploma are never explained.
5. **NID-ASSIGN's uncertain branch is missing from NID-ASSIGN itself** (lines 106-109).
   - The rule lists only two outcomes: a name match, or FAIL.
   - REQ-08/09 (line 124) says NID-ASSIGN gives a FLAG reason for an NID it could not assign with certainty, and the 4.2 heading runs NID rules on unassigned NIDs.
6. **"Notarised" is worded 7 different ways** (Section 0 lines 44-52, against NID-02, BIRTH-02, FRC-05, TRADE-02, EMP-02, DEATH-03, ACAD-05).
   - Section 0 never says whether "notarised" means the notary text AND a stamp.
   - NID-02 reads as OR. FRC-05 and EMP-02 say AND. TRADE-02 and DEATH-03 just say "notarised". ACAD-05 requires the red seal, yet cites Section 0, which also accepts ring-text seals.
7. **"Exact after cleanup" is undefined** (line 33).
   - It doesn't say what cleanup removes: case, punctuation, spacing or titles.
   - Name matching decides FAIL against PASS in about ten rules.

### Nits

8. TRADE-04 covers only "Student -> FAIL" and says nothing about an owner who matches nobody. EMP-05 says "Anyone else -> FAIL". The difference looks unintentional.
9. "Reliably read" and "with certainty" are never stated to mean confidence of at least 0.90.
10. "Current date" (PASSPORT-01, FRC-04, EMP-03, DEATH-04) and "check date" (TRADE-03, STAMP-01) are probably the same thing, but the document doesn't say so.
11. Never expanded: ECA, MD / MST, bdris, BDR Form-3, the "layout reader", `hklv_online`.
12. BIRTH-03's "A different year FAILs even across New Year" is opaque without an example.
13. TAX-03 is titled "Wealth Limit" but checks "Total Income Shown".
14. "Bank-counter challans" (TAX-04) are never defined.
15. The "(needs approval)" mark is used by no rule, and the document does not list which rules are not implemented yet.
16. CHAIN-02 overlaps TIN-03 just as much as the deleted CHAIN-01 did, and the document does not explain how they differ.

Not checked: the reviewer read no other files, so it cannot say whether these terms are defined in `rulebook.md` or `docs/rulebook-supplement-draft.md`.

## How this relates to Stage 5

- Findings 6, 10 and 16 repeat Stage 5's points A, D and B, from a third independent reader.
- Findings 1 and 2 match the Zoom Out Nits 6 and 4.
- New at this stage:
  - findings 3 and 4: how pages are grouped and paired
  - finding 5: the missing uncertain branch in NID-ASSIGN
  - finding 7: what name "cleanup" removes
  - finding 8: the TRADE-04 / EMP-05 difference

# Stage 7 — Critic Review (round 1): rules/RULES-v8.md

Target: `C:\dcSS\rules\RULES-v8.md`, lines 1-336.

| Reviewer | Persona | Standard | Status | Results |
|---|---|---|---|---|
| Design | `egm-design` | feature-spec-standard | completed | 2 Blockers, 15 Majors, 3 Nits |
| Structure | `egm-structural` | feature-spec-standard | completed | 1 Blocker, 5 Majors, 9 Nits |
| Style | `egm-style` | none | completed | 11 Majors, 14 Nits |

Each reviewer ran in a fresh context with no background files.

Finding IDs below are `<reviewer>-1-<n>`, using the reviewer's own numbers: D = design, S = structure, W = style (writing).

## 1. Standard mismatch (all three Blockers)

**D-1-1, D-1-2, S-1-1.** The feature-spec standard requires these sections: Alternatives Considered, Problem Statement, Goals and Non-Goals, Architecture, and Risks and Limits. The rulebook has none of them as headed sections.

**Assessment: contest as Blockers, keep part of the idea.**
- RULES-v8 is the operating rulebook, not a proposal, and both reviewers said the standard fits it badly.
- Adding an "Alternatives Considered" section to every rules version would mostly repeat discussions you've already settled.
- Two parts of this are still worth doing:
  - **A short purpose and limits preamble.** It would say what HKLV is, who reads the verdict, that a FLAG is preferred over a wrong FAIL or PASS, and the accepted limits listed in section 4 below.
  - **Explicit non-goals.** For example, the balance amount is not checked.

## 2. Findings that 3 or more independent reviewers raised (Stages 5-7)

| # | Finding | Raised by | Assessment |
|---|---------|-----------|------------|
| 2a | **Notarisation is worded 7 ways.** NID-02 reads as stamp OR text, FRC-05 and EMP-02 say AND, ACAD-05 asks for the red seal but cites Section 0. | D-1-6, W-1-M6, Stage 5 A, Stage 6 #6 | **Fix.** Define it once in Section 0. Each rule says "notarised (Section 0)", and ACAD-05 states its red-seal exception if that is intended. First check what the code does, so the text matches it. |
| 2b | **Pass 3 is never named**, and "online API dependent" contradicts "the rules engine never goes online". | D-1-18, S-1-F2, W-1-M2, Stage 6 #2 | **Fix.** This is wording only. |
| 2c | **"Current date" and "check date" are mixed.** The month arithmetic and whether the end day counts are undefined, and only STAMP-01 and LANG-01 say "inclusive". | D-1-7, W-1-M9/M10, Stage 5 D, Stage 6 #10 | **Fix the wording.** Define "check date" and "within N months (inclusive)" once. Recording a fixed check date per case is a code change; that one is your call. |
| 2d | **The financial chain overlaps itself.** CHAIN-02 duplicates TIN-03 much as the deleted CHAIN-01 did. TRADE-04 has no "anyone else -> FAIL" clause, and when both a trade licence and an employment letter are present, TIN-03 always picks the trade licence. | D-1-8, Stage 5 B, Stage 6 #8/#16 | **Partly fix.** Add "anyone else -> FAIL" to TRADE-04 (the code already FAILs a stranger, so check that first). Merging the chain rules changes how the UI reports failures, so that one is your decision. |
| 2e | **The rest of the EMP-05 change is only in the change log.** The rule text itself doesn't say "skipped like IGNORE-01" or "low confidence is still checked". REQ-06 doesn't mention the exclusion. EMP-05 is listed last, after the checks it skips. | S-1-F6/F7, W-1-M3 | **Fix.** The change log disappears in v9, so the rule text has to be complete on its own. |
| 2f | **NID-ASSIGN has no uncertain branch**, although REQ-08/09 cite one. | W-1-M8, Stage 6 #5 | **Fix.** This is wording only; the code already gives FLAG. |
| 2g | **Terms that are never defined:** "reliably", "exact after cleanup", HKLV, ECA, MD/MST. | W-1-M4/M5, D-1-5, Stage 6 #7/#9/#11 | **Fix.** "Reliably" means confidence of 0.90 or more. Say what cleanup removes, using the rules in `names.py`. |
| 2h | **Page classification:** the order of checks isn't declared, the Affidavit signature doesn't say AND or OR, and "To Whom It May Concern" alone makes a page a solvency letter. | D-1-3, W-1-M7, Stage 5 M3, Stage 6 #3 | **Fix the text so it matches `classify.py`.** Describe the order the code already uses. Changing behaviour (for example, how JPGs are classified) is a separate decision. |

## 3. Other Majors

**Design reviewer:**
- **D-1-4** — The anchors depend on each other in a loop: the parents' names come from "the student's" birth certificate before BIRTH-05 has confirmed whose certificate it is. Line 103 says a parent can be identified by passport, but REQ-08/09 don't accept a passport.
  - **Assessment: fix the wording.** Delete "or passport", or say how a parent's passport is handled.
- **D-1-9** — The online checks prove that a document exists, not whose it is. A copied apostille QR code or someone else's challan for the same amount would pass.
  - **Assessment: real risk.** Comparing the register's details with the case is new code. At the very least, list it under accepted limits.
- **D-1-10** — STAMP-01 silently ignores an unreadable or future date, which creates an evasion path.
  - **Assessment: this is your v5 decision.** Record it as an accepted risk, or change it to FLAG. Your call.
- **D-1-11** — The rules don't say which checks an affidavit can fix. A cheap affidavit could pass someone outside the family off as a sponsor.
  - **Assessment: real risk.** List which rules an affidavit can cover. Consider allowing it to raise financial-chain rules only to FLAG. Your call.
- **D-1-12** — The online checks have no timeout, retry, rate limit or cache, and a changed "not found" page could be misread as NOT_FOUND.
  - **Assessment: an engineering concern, not rulebook text.** Check `hklv_online` separately.
- **D-1-13** — The 0.90 and 0.85 thresholds have no calibration evidence behind them.
  - **Assessment: accepted limit.** Name the OCR engine (PaddleOCR) in the preamble.
- **D-1-14** — "A misread can't land on the exact number" is stated as a certainty.
  - **Assessment: fix the wording** to "is very unlikely to".
- **D-1-15** and **W-1-M11** — BANK-04 and an unsure ACAD-06 report PASS for checks that never happened.
  - **Assessment: wording, plus a decision.** Make the PASS text say "not checked", and list the balance as a non-goal. Changing it to a separate outcome is a UI change.
- **D-1-16** — The EMP-05 skip:
  - a letter whose name matches both the student and a parent should be FLAGged, not skipped
  - the order of checks should be written down
  - **Assessment: fix.** This edge case is cheap to add to the code and the text.
- **D-1-17** — BANK-03's fallback can PASS by matching the date on a statement for a different account.
  - **Assessment: check the code.** If confirmed, it's a real bug.

**Structure reviewer:**
- **S-1-F3** — Subsections such as "4.1 PASSPORT" are plain text, not headings.
  - **Assessment: fix.** Make them `###` headings. That also improves the Obsidian and graph output.
- **S-1-F8** — Two rule bullets have no rule ID: relation matching in 4.4, and "both a trade licence and an employment letter" in 5.1.
  - **Assessment: fix.** Give them IDs, or fold them into FRC-03 and the CHAIN rules.
- **S-1-F13** — Lines 21-24 run together into a single paragraph when rendered.
  - **Assessment: fix.**

**Style reviewer:**
- **W-1-M1** — "The single, complete set of rules the engine applies" goes further than the engine does.
  - **Assessment: fix the wording.**

## 4. Accepted limits to record (proposed for the preamble)

- The balance and the sponsor's ability to pay are not checked (BANK-04).
- An online check proves the apostille or challan exists, not that it belongs to this student (ACAD-01, TAX-04).
- STAMP-01 ignores dates read below 85% confidence. This was the owner's decision on 2026-11-12.
- The OCR confidence thresholds are not calibrated against measured error rates.

## 5. Nits

- **Design:** D-1-19 (a name matching two anchors), D-1-20 (FRC-03 should reference DEATH-01).
- **Structure:**
  - S-1-F4/F5: the "4.6b" and "1.1" numbering
  - S-1-F9/F10/F11/F12: list placement and title consistency
  - S-1-F14/F15: Section 0 referring to itself; HKLV never spelled out
- **Style:**
  - W-1-N1 to N14: contractions, the "forgery" wording, mixed 0.90 / 85% notation, "silently ignored", the cryptic New Year example, CHAIN-02 giving only examples, the hosts paragraph in Section 7, unnumbered rules
  - "License" vs "licence" and "Acknowledgement" vs "Acknowledgment": keep the spellings that are OCR keywords, and say so in the text.

## 6. If you choose "Resolve findings with agent"

All edits go into a new **RULES-v9.md**, as your policy requires. v8 is never edited.

I'd group the work like this:
1. **Wording only.** The rules stay the same:
   - 2a, 2b, 2c, 2e, 2f, 2g and 2h
   - D-1-4, D-1-14
   - S-1-F3, F8, F13
   - W-1-M1
   - the Nits
   - the preamble with the accepted limits
2. **Small rule and code fixes, each with its own tests:**
   - TRADE-04 "anyone else -> FAIL"
   - the D-1-16 FLAG for a name matching both the student and a parent
   - D-1-17, if the bug is confirmed
3. **Your decisions:**
   - D-1-9 (online ownership)
   - D-1-10 (STAMP-01)
   - D-1-11 (affidavit scope)
   - merging the chain rules
   - a fixed check date per case

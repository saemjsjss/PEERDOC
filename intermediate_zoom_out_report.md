# Stage 8 — Intermediate Zoom Out Review: rules/RULES-v8.md

Target: `C:\dcSS\rules\RULES-v8.md`, lines 1-336. The file has not changed since Stages 5-7.
Reviewer: `egm-zoom-out`, in a fresh context. It read the Stage 5-7 reports and searched the repo for reuse.
Focus: would the fixes proposed in Stages 5-7 bloat or misplace content, or miss a simpler route?

There are no Blockers. The main result is that `critic_report.md` section 6, followed as written, would cause three problems:
- It would put the same text in a second place where it can drift.
- It would break the graph and Obsidian generators.
- It would ask you to decide something the code has already settled.

I checked M2 and M3 against the code; both claims hold.

## Major

**M1. Classification and page grouping already have a home: `docs/pass1-extraction.md`.**
- That document already covers:
  - the classification order (lines 78-116)
  - how pages are grouped (`group.py`)
  - what the "academic block" is
  - field-finding conventions
  - where confidence comes from
- It already disagrees with RULES-v8 in two places:
  - **Affidavit:** RULES line 90 lists "Affidavit, Notary Public, Same person". pass1 says "Notary Public" alone is not a signature.
  - **Solvency letter:** RULES line 72 accepts "To Whom It May Concern" alone. pass1 requires it together with bank and account words.
- Critic 2h ("describe the order the code already uses") would create a third copy.
- **Direction:**
  - Keep only the signatures, plus a pointer to pass1-extraction.md, in Section 1.
  - Fix the two signatures that disagree.
  - Move the OCR misread examples there (D60631, NOTARY PULIC, the Form-3 square, "layout reader", red seal found by colour). The policy sentence stays in the rulebook.

**M2. Turning subsections into `###` headings would break both generators.** This finding overrides Stage 7's S-1-F3.
- `make_rules_graph.py` finds subsections with `^(\d+\.\d+b?) ` at the start of a line. `make_obsidian_vault.py` uses the same parser.
- New or merged rule IDs, or a retitled TAX-03, also need `frontend/src/lib/rules.ts`, the UI's rule titles.
- **Direction:** drop F3, or change the parser in the same commit and regenerate.

**M3. A fixed check date per case already exists.** This removes critic 2c from your decision list.
- `CaseFile.evaluation_date` is set in `build_case` (`src/hklv_extract/build.py`).
- The API accepts it and defaults to today (`src/hklv_api/app.py`).
- Every date rule reads it.
- **Direction:** add one Section 0 line: "Check date = the case's evaluation date (default: upload day); 'within N months' is inclusive." Then use "check date" everywhere.

**M4. The "wording only" group is really a check of the rules against the code.**
- 2a, 2g, 2h, TRADE-04 and D-1-17 all start with "first check the code".
- **Direction:** before drafting v9, make one list of each rule ID and the code that implements it, and write v9 from that list. Fixing one finding at a time would carry today's disagreements into v9.

**M5. The EMP-05 skip is in the wrong section, and Stage 5's suggested move is also wrong.**
- Deciding that a letter is "the student's own" needs StudentRef, which comes from the passport in Pass 2. So it doesn't belong in Pass 1 (Section 1), as Stage 5 proposed. It doesn't belong as the last bullet of 4.6b either.
- Critic 2e is partly overstated: lines 220-221 already state the skip, the REQ-06 exclusion and the chain exclusion. Only "a low-confidence name is still checked" is missing.
- **Direction:**
  - Add one assignment bullet to Section 2, next to NID-ASSIGN: student, parent, or both (FLAG, per D-1-16), plus the low-confidence case.
  - EMP-05 then checks only letters in a parent's name.
  - This settles 2e, D-1-16 and the "write the order down" point at once.

## Nits

- **N1.** Don't name the OCR engine in the rulebook (D-1-13). It's PP-OCRv6 plus PaddleOCR-VL, documented in pass1-extraction.md. State only the policy: the thresholds are not calibrated.
- **N2.** Name cleanup (2g) needs one sentence of policy, not the code from `normalize_name` restated. It should say that titles are kept: pass1 says "MD X" and "X" are different names.
- **N3.** Keep the preamble to about 10 lines with no Alternatives or Goals sections. Say "balance not checked" once.
- **N4.** Keep caching, retries and timeouts for the online checks out of the rulebook.
- **N5.** Generate the vault and graph only for the current version. The full-copy policy for rules stays, as you instructed.
- **N6.** pass1-extraction.md line 266 says "no LANG rules yet", but `language.py` implements LANG-01/02. Fix it if that document takes the moved content.

## Effect on the Stage 7 plan

| Stage 7 item | After Stage 8 |
|---|---|
| S-1-F3, `###` headings | Drop, or change the parser in the same commit. |
| 2c, fixed check date | Not a decision: it already exists. One Section 0 line covers it. |
| 2h, classification order | Point to pass1-extraction.md and fix the 2 signatures that disagree. |
| 2e and D-1-16, EMP-05 | One Section 2 assignment bullet covers both. |
| D-1-13, name the OCR engine | Drop it; state only that the thresholds are not calibrated. |
| Group 1, "wording only" | Do a rules-against-code check first, then write v9. |

The decisions still yours: D-1-9 (online ownership), D-1-10 (STAMP-01), D-1-11 (affidavit scope), and merging the chain rules.

Not checked: whether `classify.py` matches pass1-extraction.md, and the suspected BANK-03 bug (D-1-17).

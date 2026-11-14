# Stage 5 — Initial Zoom Out Review: rules/RULES-v8.md

Target: `C:\dcSS\rules\RULES-v8.md`, lines 1-335 (whole file; there is no implementation plan, so Stage 9 does not apply).
Reviewers: Zoom Out (`egm-zoom-out`) and Inventive Catalyst (`egm-inventive-catalyst`), each in a fresh context with no conversation history.
Background files: none given. The Zoom Out reviewer also read `README.md` (one line).

Neither reviewer found a Blocker. The two worked independently and agree on four of their main points.

## Where both reviewers agree

| # | Finding | Zoom Out | Catalyst |
|---|---------|----------|----------|
| A | Notarisation is defined in Section 0, then restated in 7 rules with wording that disagrees. NID-02 "stamp / Advocate" reads as OR. FRC-05 and EMP-02 say text AND stamp. ACAD-05 asks for the red seal, while Section 0 also accepts a ring-text seal. It is unclear whether a transcript with a ring-text seal passes. | Major 1 | Major M5 |
| B | The financial-chain checks overlap, so one wrong document gives 2-4 FAILs. A student-held account fails BANK-01 and CHAIN-04. A student TIN fails TIN-03 and CHAIN-03. CHAIN-04 re-fails a missing document that REQ-05 / REQ-06 already fail. The "reviewer picks" FLAG fires even when only one income document fits the TIN and the bank. | Major 2 | Major M1 |
| C | The low-confidence exceptions in Section 0 are really three unnamed policies: (a) a low-confidence value is accepted if it exactly matches an independent second reading, (b) only presence matters, (c) unreliable evidence is ignored. STAMP-01 uses its own 85% threshold. STAMP-01 and ACAD-06 throw away possible FAIL evidence silently, against "never a guess". | Nit 1 | Major M2 |
| D | "Current date" (PASSPORT-01, FRC-04, EMP-03, DEATH-04) and "check date" (TRADE-03, STAMP-01) are mixed. Running the same case a month later can turn PASS into FAIL. | Nit 3 | Major M4 |

## Findings raised by one reviewer

**Major: OCR workarounds written in as policy** (Zoom Out Major 3)
- Examples:
  - the agency "Trade Licence No." misread "D60631"
  - "NOTARY PULIC" counts, "REG NO TAREK" does not
  - the filled square on the old Form-3
  - "when the layout reader returns only part of the table"
  - the red seal "found by colour"
  - the MRZ digit map
  - the "Amount in words" line
- These describe how text is extracted, not what makes an application valid. They belong next to the extraction code and its fixtures.

**Major: an unrecognised page becomes a hard FAIL** (Catalyst Major M3)
- IGNORE-01 drops pages silently. If the family certificate page is not recognised, REQ-04 FAILs. That is a guess presented as an error.
- Proposal: keep unrecognised pages, and turn a REQ FAIL into a FLAG when an unrecognised page could be the missing document.
- The order in which document types are recognised should be declared once in Section 1. It is currently patched rule by rule; the new EMP-05 skip, for example, sits in Section 4.

**Major / Nit: each version is a full copy of the file** (Zoom Out Major 4, Catalyst Nit N1)
- Git already keeps the history. Every version also gets its own Obsidian vault.
- The policy says "old wording deleted", yet tombstones are kept (TAX-02, CHAIN-01).

**Nits:**
- Section 0 should say what happens when the student's or a parent's reference name is missing. Only LANG-02 does today; Section 0 should say FLAG for every rule. (Zoom Out)
- "3-pass architecture" names only Pass 1 and Pass 2. (Zoom Out)
- Rules that never tell the reviewer anything:
  - BANK-04 always PASSes, as if a balance check had happened.
  - TAX-01 repeats REQ-10.
  - The "(needs approval)" mark is unused. (Zoom Out)
- Missing context: "HKLV" is never spelled out, the destination country is not named, and the rulebook never says whether a wrong FAIL or a wrong PASS is worse. (Zoom Out)
- Online look-ups are repeated on every run, so a network failure can turn an earlier PASS into a FLAG. Proposal: cache the results. (Catalyst)

## Where I disagree with the reviewers

- **The versioning finding goes against your standing instruction.** You asked for a new complete RULES-vN file for every change, and for old files never to be edited. The reviewers did not know that. One part of their point still holds: tombstones for deleted rules contradict "old wording deleted", so the policy should say they are kept so that rule IDs are never reused.
  - Their suggestion to generate only the current vault and graph is cheap to adopt.
- **Merging the chain checks (finding B) changes how failures are reported.** The UI would show fewer FAIL lines but name the cause less precisely. Today, a student-held account produces a clear BANK-01 message. The reviewers name this cost too.
- **Finding C, policy (c), is your decision from the v5 changes.** You asked for STAMP-01 below 85% and for an unsure ACAD-06 to be ignored, not flagged. The reviewers are right that this conflicts with "never a guess" in Section 0. The fix may be wording ("these rules deliberately ignore unsure readings") rather than behaviour.
- **The OCR-workaround finding is right about where the text belongs.** But some of these lines are exactly what you approved as policy, for example the agency letterhead not being a trade licence. Moving them means separating the policy sentence from the example misread, not deleting them.

## Not covered at this stage

- Whether the engine code matches these rules.
- Whether v1-v7 and `rulebook.md` agree with v8.
- Domain judgement on the thresholds (the exact date match in BANK-03, 5,000,000 BDT in TAX-03).

---
section: 4
status: approved
outcomes: [FAIL]
tags:
  - section/4
  - kind/rule
  - status/approved
  - outcome/FAIL
---

# FRC-02 — Identity

Section: [[Section 4 - Document-Specific Rules]]
Subsection: 4.4 FAMILY RELATIONSHIP CERTIFICATE (FRC)

table must have a row whose relation is SELF or a synonym for the applicant themself (HIMSELF, HERSELF, MYSELF, ONESELF, APPLICANT, STUDENT, CANDIDATE), with a name matching [[StudentRef]]. Missing -> FAIL. An "Applicant Name:" line under the table counts as an APPLICANT row. *(approved)*

## Notes
- Relations are matched by word: "Father (Late)", "Father's", "Self (Applicant)" and Bangla পিতা / মাতা / নিজ count; "Father-in-law" and "Step Mother" do not. An unknown Bangla relation -> FLAG.

## Depends on
- [[AFFIDAVIT]]
- [[StudentRef]]

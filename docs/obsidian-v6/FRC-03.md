---
section: 4
status: approved
outcomes: [FAIL, FLAG]
tags:
  - section/4
  - kind/rule
  - status/approved
  - outcome/FAIL
  - outcome/FLAG
---

# FRC-03 — Parents

Section: [[Section 4 - Document-Specific Rules]]
Subsection: 4.4 FAMILY RELATIONSHIP CERTIFICATE (FRC)

rows for FATHER and MOTHER, names matching [[FatherRef]] and [[MotherRef]]. Missing -> FAIL. When the layout reader returns only part of the table, the dropped FATHER / MOTHER cells are unreadable rows -> FLAG. *(approved)* A parent who has died may have no row: the certificate names them as "Late <name>" (matching [[FatherRef]] / [[MotherRef]]) and their death certificate is in the case -> that parent passes. *(approved)*

## Notes
- Relations are matched by word: "Father (Late)", "Father's", "Self (Applicant)" and Bangla পিতা / মাতা / নিজ count; "Father-in-law" and "Step Mother" do not. An unknown Bangla relation -> FLAG.

## Depends on
- [[AFFIDAVIT]]
- [[FatherRef]]
- [[MotherRef]]

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

# DEATH-01 — Assignment

Section: [[Section 4 - Document-Specific Rules]]
Subsection: 4.11 DEATH CERTIFICATE (replaces a parent's NID)

deceased must match [[FatherRef]] or [[MotherRef]]. Student or anyone else -> FAIL. Two certificates for the same parent -> FLAG.

## Depends on
- [[AFFIDAVIT]]
- [[FatherRef]]
- [[MotherRef]]

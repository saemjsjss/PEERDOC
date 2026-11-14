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

rows for FATHER and MOTHER whose names match [[FatherRef]] and [[MotherRef]]. No such row in a reliably read table -> FAIL; a row the reader could not return is unreliable -> FLAG. A parent who has died may have no row: the certificate names them "Late <name>" (matching their reference name) and their Death Certificate is assigned to them ([[DEATH-01]]) -> that parent passes. *(approved)*

## Depends on
- [[AFFIDAVIT]]
- [[DEATH-01]]
- [[FatherRef]]
- [[MotherRef]]

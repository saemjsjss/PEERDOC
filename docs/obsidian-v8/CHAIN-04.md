---
section: 5
status: approved
outcomes: [FAIL, FLAG, PASS]
tags:
  - section/5
  - kind/rule
  - status/approved
  - outcome/FAIL
  - outcome/FLAG
  - outcome/PASS
---

# CHAIN-04 — Bank

Section: [[Section 5 - Global Cross-Checks]]
Subsection: 5.1 The Financial Chain (TIN, Trade License / Employment Certificate and Bank Solvency)

each Bank Solvency's account holder must be the same parent as the Trade License owner (or the Employment Certificate's employee). Same parent -> PASS; the other parent, the student, or nobody in the family -> FAIL; a name read with low confidence or not certainly identified -> FLAG. No Bank Solvency or no income document -> FAIL ([[REQ-05]] / [[REQ-06]] name which). One result per Bank Solvency. *(approved)*

## Notes
- Both a Trade License and an Employment Certificate submitted -> FLAG (reviewer picks which one forms the chain). One link unreadable or duplicated -> FLAG, but a link reliably in the student's name still FAILs.

## Depends on
- [[BANK-01]]
- [[EMP-05]]
- [[REQ-05]]
- [[REQ-06]]
- [[TRADE-04]]

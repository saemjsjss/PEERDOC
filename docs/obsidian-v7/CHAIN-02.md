---
section: 5
status: rulebook
outcomes: [FAIL, PASS]
tags:
  - section/5
  - kind/rule
  - status/rulebook
  - outcome/FAIL
  - outcome/PASS
---

# CHAIN-02

Section: [[Section 5 - Global Cross-Checks]]
Subsection: 5.1 The Financial Chain (TIN, Trade License / Employment Certificate and Bank Solvency)

TIN and the income document must belong to the same parent (TIN=Father, Trade=Father -> PASS; TIN=Father, Trade or Employment=Mother -> FAIL). A link that reliably matches no family member -> FAIL.

## Notes
- Both a Trade License and an Employment Certificate submitted -> FLAG (reviewer picks which one forms the chain). One link unreadable or duplicated -> FLAG, but a link reliably in the student's name still FAILs.

## Depends on
- [[EMP-05]]
- [[TIN-03]]
- [[TRADE-04]]

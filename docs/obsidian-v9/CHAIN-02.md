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

# CHAIN-02 — Same Parent

Section: [[Section 5 - Global Cross-Checks]]
Subsection: 5.1 The Financial Chain

the TIN Certificate, the income document (Trade License or Employment Certificate) and every Bank Solvency must belong to the same parent. Only documents assigned to a parent by their own rule ([[TIN-03]], [[TRADE-04]], [[EMP-05]], [[BANK-01]]) are compared; when one of the three has none, CHAIN-02 gives no result (the document's own rule, or [[REQ-05]] / [[REQ-06]] / [[REQ-07]], reports it). One parent has both a TIN and an income document and every compared account holder is that parent -> PASS; an account holder is the other parent -> FAIL. No parent has both (TIN = father, income = mother) -> FAIL. Both parents have both: every compared account holder the same parent -> PASS, otherwise -> FLAG (the reviewer picks). *(approved)*

## Depends on
- [[BANK-01]]
- [[EMP-05]]
- [[REQ-05]]
- [[REQ-06]]
- [[REQ-07]]
- [[TIN-03]]
- [[TRADE-04]]

## Feeds
- [[CHAIN-04]]

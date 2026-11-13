---
section: 4
status: approved
outcomes: [FAIL, FLAG, PASS]
tags:
  - section/4
  - kind/rule
  - status/approved
  - outcome/FAIL
  - outcome/FLAG
  - outcome/PASS
---

# BANK-02 — Account Number

Section: [[Section 4 - Document-Specific Rules]]
Subsection: 4.5 BANK SOLVENCY & STATEMENT (BANK-01..03: one result per solvency letter)

solvency account number must match the statement's. Mismatch -> FAIL. A number of 8+ digits read with low confidence PASSes when it equals the other document's number digit for digit, whether that one was read reliably or not (a misread can't land on the exact number); otherwise low confidence -> FLAG. *(approved)*

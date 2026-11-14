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

# BANK-03 — Date Match

Section: [[Section 4 - Document-Specific Rules]]
Subsection: 4.5 BANK SOLVENCY & STATEMENT (BANK-01..03 and BANK-05: one result per solvency letter)

the solvency letter date (top of the letter) must be identical to the date of the statement with the same account number (Generation Date, As on, Print Date); one day apart -> FAIL. The statement is picked by number only when both numbers are reliable, or there is only one statement. Otherwise every statement whose number is not reliably different is compared: a date match -> PASS, no match -> FLAG, never FAIL. *(approved)*

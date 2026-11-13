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

# BANK-03 — Date Match

Section: [[Section 4 - Document-Specific Rules]]
Subsection: 4.5 BANK SOLVENCY & STATEMENT (BANK-01..03: one result per solvency letter)

solvency date (top of letter) vs statement date (Generation Date, As on, Print Date) of the statement with the same account number. Dates must be identical (one day apart -> FAIL). The statement is chosen by number only when both numbers were read reliably (or there is one statement); otherwise no statement is picked on shaky digits, and the result is FLAG unless some statement's date matches. *(approved)*

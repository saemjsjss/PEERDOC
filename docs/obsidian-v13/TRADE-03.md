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

# TRADE-03 — Validity

Section: [[Section 4 - Document-Specific Rules]]
Subsection: 4.6 TRADE LICENSE

the fiscal year runs 1 July - 30 June. The licence PASSes if, on the check date, it is valid until at least the 30 June that ends the current fiscal year (from a "Valid up to" date, or the fiscal year printed: 2026-2027 = valid until 30-06-2027), OR it was issued on or after the 1 July that started that fiscal year. Checked in January 2027: valid until 30-06-2027, or issued since 01-07-2026. Neither -> FAIL, also when no such date is found. A date that would pass but is unreliable -> FLAG. An issue date after the check date -> FLAG (a misread). A renewal page listing several years counts the latest. *(approved)*

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

# STAMP-01 — Date

Section: [[Section 4 - Document-Specific Rules]]
Subsection: 4.12 NOTARY AND TRANSLATION DATES

on every document, each notary date (the date on or beside the notary's stamp: "09 JUN 2026", "Date: 23/06/2026") and each translator date (beside "Translated by") read with at least 85% OCR confidence must be within 3 months of the check date (inclusive). Older -> FAIL. Below 85% confidence, or after the check date (a misread), the date is ignored: no PASS, FLAG or FAIL. Translation and notarisation may be on different days. Document dates printed near the notary block (publication date, issue date, a birth date in a table) are not notary dates.

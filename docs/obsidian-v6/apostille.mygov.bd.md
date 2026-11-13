---
section: 7
status: rulebook
outcomes: [FAIL, FLAG, PASS]
tags:
  - section/7
  - kind/api
  - status/rulebook
  - outcome/FAIL
  - outcome/FLAG
  - outcome/PASS
---

# apostille.mygov.bd — e-Apostille register

Section: [[Section 7 - Online Checks (ACAD-01, TAX-04)]]

the application number from the QR (only from an https link on apostille.mygov.bd) is looked up at `https://apostille.mygov.bd/application-details/<n>`. Confirmed -> VERIFIED (PASS); "not found" -> NOT_FOUND (FAIL); anything else -> UNAVAILABLE (FLAG). This proves the apostille exists in the register, not that the scan matches it.

## Feeds
- [[ACAD-01]]

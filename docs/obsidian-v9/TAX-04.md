---
section: 4
status: rulebook
outcomes: [FAIL, FLAG, PASS]
tags:
  - section/4
  - kind/rule
  - status/rulebook
  - outcome/FAIL
  - outcome/FLAG
  - outcome/PASS
---

# TAX-04 — Challan Verification

Section: [[Section 4 - Document-Specific Rules]]
Subsection: 4.9 INCOME TAX (optional)

the challan number comes from the QR, else the printed text; the amount from "Total Amount". It is checked online (Section 7): the website amount equals the printed amount -> PASS; they differ -> FAIL; a refunded challan ("not valid for any service") -> FAIL; no such challan -> FLAG (a misread number looks the same); the internet fails -> FLAG. A bank-counter challan (paid at a bank, without an automated `YYYY-NNNNNNNNNN` number) -> FLAG. QR codes on the Income Tax Certificate and Acknowledgment are ignored.

## Depends on
- [[TAX-01]]
- [[achallan.gov.bd]]

## Feeds
- [[TAX-02]]
- [[achallan.gov.bd]]

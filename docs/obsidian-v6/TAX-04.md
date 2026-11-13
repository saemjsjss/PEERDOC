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

challan number read from the QR first, else the printed text; printed amount from "Total Amount", never the line under "Amount in words". Checked online (Section 7): website amount = printed amount -> PASS; mismatch -> FAIL; refunded challan ("not valid for any service") -> FAIL; no such challan -> FLAG (a misread number looks the same); internet fails -> FLAG. Bank-counter challans -> FLAG (manual review). QR codes on the Income Tax Certificate and Acknowledgment are ignored.

## Depends on
- [[TAX-01]]
- [[achallan.gov.bd]]

## Feeds
- [[TAX-02]]

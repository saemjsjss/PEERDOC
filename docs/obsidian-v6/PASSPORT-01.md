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

# PASSPORT-01 — Expiry

Section: [[Section 4 - Document-Specific Rules]]
Subsection: 4.1 PASSPORT

expiry before the current date -> FAIL; less than 12 months from the current date -> FAIL (exactly 12 months passes). The expiry checked is the MRZ one (check-digit verified); a low-confidence MRZ expiry is FLAG even if it looks long past. MRZ and print mismatch -> FLAG: covers the name (word order, spacing and MRZ digit slips ignored, as in 2.1) and a reliably read printed expiry that differs from the MRZ expiry. *(approved)*

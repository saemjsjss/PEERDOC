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

the MRZ expiry (check-digit verified) must be at least 12 months after the check date; earlier, or already past -> FAIL. MRZ and printed page disagree -> FLAG: the names do not match (Section 0, with MRZ digits read as in 2.1), or a reliable printed expiry differs from the MRZ expiry. *(approved)*

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

# NID-03 — Number Match

Section: [[Section 4 - Document-Specific Rules]]
Subsection: 4.2 NID (assigned to the father, mother or student, and also an NID that could not be assigned)

card number vs translation number. Equal -> PASS; 1-2 digits differ -> FLAG; 3 or more -> FAIL. Same length: count the differing positions; a dropped or added digit: edit distance. A low-confidence number is confirmed as in Section 0. *(approved)*

## Feeds
- [[TIN-02]]

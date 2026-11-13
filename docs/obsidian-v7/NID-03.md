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
Subsection: 4.2 NID (assigned to Father, Mother or Student; also run on an NID that could not be assigned)

card vs translation. Exact -> PASS; 1-2 digits differ -> FLAG; 3+ -> FAIL. Same length: count differing positions; a dropped or added digit: edit distance. A low-confidence reading still PASSes when both numbers are 8+ digits and equal digit for digit; otherwise low confidence -> FLAG. *(approved)*

## Feeds
- [[TIN-02]]

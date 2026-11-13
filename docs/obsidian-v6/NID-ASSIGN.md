---
section: 2
status: rulebook
outcomes: [FAIL]
tags:
  - section/2
  - kind/rule
  - status/rulebook
  - outcome/FAIL
---

# NID-ASSIGN

Section: [[Section 2 - Identity Anchors & Assignment (Pass 2)]]
Subsection: 2.2 NID-ASSIGN: for every NID (Old or Digital), the cardholder name:

for every NID (Old or Digital), the cardholder name:
Matches [[StudentRef]] -> Student NID. Matches [[FatherRef]] -> Father NID. Matches [[MotherRef]] -> Mother NID.
Matches nobody -> FAIL ("NID belongs to an unknown person or sibling").

## Depends on
- [[AFFIDAVIT]]
- [[FatherRef]]
- [[MotherRef]]
- [[StudentRef]]

## Feeds
- [[REQ-08]]
- [[REQ-09]]

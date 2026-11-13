---
section: 3
status: rulebook
outcomes: [FAIL, FLAG]
tags:
  - section/3
  - kind/rule
  - status/rulebook
  - outcome/FAIL
  - outcome/FLAG
---

# REQ-09

Section: [[Section 3 - Required Documents]]

no Mother NID AND no Mother Death Certificate -> FAIL. [[REQ-08]]/09 count only a document assigned to that parent by name; a sibling's NID does not count. If none is assigned but an NID or Death Certificate that could be this parent's could not be assigned with certainty -> FLAG (the reason is given by [[NID-ASSIGN]]). A document whose name clearly mismatches the parent never softens the FAIL.

## Depends on
- [[NID-ASSIGN]]

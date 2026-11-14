---
section: 5
status: rulebook
outcomes: [FAIL, FLAG]
tags:
  - section/5
  - kind/rule
  - status/rulebook
  - outcome/FAIL
  - outcome/FLAG
---

# AFFIDAVIT — 5.2 Affidavit Coverage

Section: [[Section 5 - Global Cross-Checks]]
Subsection: 5.2 Affidavit Coverage

On a name mismatch (e.g. a spelling difference) the engine looks for an Affidavit.
The Affidavit is notarised (Section 0), states that both spellings are the "same person", and matches the student or parent -> the names match.
No Affidavit covers the mismatch -> the rule's own mismatch outcome stands (FAIL, or FLAG where the rule says FLAG, as [[ACAD-04]]).

## Depends on
- [[ACAD-04]]

## Feeds
- [[ACAD-01]]
- [[ACAD-04]]
- [[BIRTH-05]]
- [[FRC-02]]
- [[FRC-03]]
- [[LANG-02]]
- [[TIN-03]]

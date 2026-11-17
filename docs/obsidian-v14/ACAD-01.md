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

# ACAD-01 — e-Apostille

Section: [[Section 4 - Document-Specific Rules]]
Subsection: 4.8 ACADEMIC CERTIFICATES (SSC / HSC: secondary / higher secondary school certificates;

the apostille is looked up in the official register (Section 7) and the register's own copy must be the student's. *(approved)* * Number: from the QR; when the QR can't be decoded, from the "8. Nº" line printed on the page. A QR that links to another site or uses http -> FAIL. Neither read -> FLAG. QR number and a reliable printed No. that differ: the QR's number is looked up as usual; a FAIL from the register or owner check stands, any other result -> FLAG. * Register: says not found -> FAIL (FLAG when only the printed No. was looked up: a misread number looks the same). The internet fails -> FLAG. * Owner: the register's copy of the document is read like a submitted one. It must hold the kind (certificate or transcript) and level of the document that follows the apostille, and be in the student's name ([[StudentRef]], Section 0). A register copy in another name, of another level, or with a different reliable board registration number than the document -> FAIL. A register copy that could not be downloaded or read, or a name that is not reliable -> FLAG; a copy read only in part never gives the "other level" FAIL (the missing page may be the one). All match -> PASS.

## Depends on
- [[AFFIDAVIT]]
- [[StudentRef]]
- [[apostille.mygov.bd]]

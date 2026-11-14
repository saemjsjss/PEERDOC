---
section: 7
status: rulebook
outcomes: []
tags:
  - section/7
  - kind/api
  - status/rulebook
---

# apostille.mygov.bd — e-Apostille register

Section: [[Section 7 - Online Checks (ACAD-01, TAX-04)]]

the application number (from an https QR link on apostille.mygov.bd, or the printed No.) is looked up at `https://apostille.mygov.bd/application-details/<n>`. For a confirmed number, the register's details are fetched from `https://api.apostille.mygov.bd/api/v1/application-details/<n>` (the lookup behind mofa-servicedirectory.apostille.mygov.bd): the apostille date, the titles of the apostilled documents and their page images. The images are downloaded at once (their links expire), read by OCR and not stored.

## Feeds
- [[ACAD-01]]

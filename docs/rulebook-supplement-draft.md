# Rulebook v2.5 supplement (DRAFT, needs approval)

Rulebook v2.5 names the Employment Certificate (REQ-06, section 4.6, 5.1) and the
Death Certificate (REQ-08, REQ-09) but gives them no rules. These are the rules the
engine now applies. Nothing here changes `rulebook.md`.

## 4.6b EMPLOYMENT CERTIFICATE (instead of a Trade License)

* EMP-01 (Format): If Bangla, must have English translation. If missing -> FAIL.
* EMP-02 (Notary): Must be notarized (Notary Public/Advocate text AND a stamp). If missing -> FAIL.
* EMP-03 (Date): Issue date must be within 3 months of the current date. If older -> FAIL.
  *(Differs from TRADE-03's "current fiscal year": an employer's letter should be recent.)*
* EMP-04 (Current): Must state the person is employed now. Experience or release letter -> FAIL.
* EMP-05 (Employee): Employee name must match FatherRef or MotherRef. Student or anyone else -> FAIL.

Financial chain (5.1): the Employment Certificate employee takes the Trade License
owner's place in CHAIN-01..03. TIN=Father with Employment=Mother -> FAIL.
If both a Trade License and an Employment Certificate are submitted -> FLAG
(reviewer picks which one forms the chain).
When one link is unreadable or duplicated, CHAIN-01 is FLAG, but a link that is reliably in
the student's name still FAILs CHAIN-03 (and CHAIN-02), and a link that reliably matches no
family member still FAILs CHAIN-02.

## 4.11 DEATH CERTIFICATE (replaces a parent's NID)

* DEATH-01 (Assignment): Deceased name must match FatherRef or MotherRef.
  Student or anyone else -> FAIL. Two certificates for the same parent -> FLAG.
* DEATH-02 (Format): If Bangla, must have English translation. If missing -> FAIL.
* DEATH-03 (Notary): Must be notarized. If missing -> FAIL.
* DEATH-04 (Date): Date of death must be readable and not after the current date. Otherwise -> FLAG.
* DEATH-05 (Consistency): No financial document may present the deceased parent as a living
  sponsor. An Employment Certificate for them issued after the date of death -> FAIL. Any other
  Employment Certificate, Trade License or TIN in their name -> FLAG.

REQ-08 / REQ-09: satisfied by an NID or a Death Certificate *assigned to that parent by
name*. A sibling's NID does not count. If no document is assigned to the parent but an
NID or Death Certificate that *could* be this parent's could not be assigned with certainty
-> FLAG instead of FAIL. A document whose name clearly mismatches this parent never softens
the FAIL.

## Classification signatures (for Pass 1, section 1.1)

Not used by the rules engine yet; proposed for the OCR pass:

* Employment Certificate: (Employment Certificate OR Experience Certificate OR "is working"
  OR "is employed") AND an employer letterhead.
* Death Certificate: Death Registration Number OR Death Certificate OR মৃত্যু নিবন্ধন.

## Section 6 additions

* An empty list of results -> FLAG (nothing was checked, so it can't be PASS).
* Until every rule in the rulebook is implemented, the engine adds an `ENGINE-COVERAGE`
  FLAG that names the unchecked rules, so no case can get a clean PASS by accident.

## Same conventions as the rest of the engine

Unreadable or low-confidence values -> FLAG, never a guess. Name matching is exact after
cleanup; a notarised same-person affidavit bridges spelling differences (5.2).

## Interpretations made while implementing sections 4.1-4.10 (need approval)

Where the rulebook text leaves a case open, the engine does the following. Each line is
one decision; change any of them and the matching rule changes.

**Approved by the project owner on 2026-11-11:** ACAD-02 (pairs per level), ACAD-03
(unlisted combinations FLAG) and TIN-03 (Employment Certificate when there is no Trade
License). BIRTH-02 stays FLAG when the layout model misses a red foil seal; colour-based
seal detection is deferred to a later update. The other lines below still await review.

**4.1 Passport.** PASSPORT-01: expiry exactly 12 months after the evaluation date passes.
"MRZ and Print mismatch" covers both the name (word order and spacing ignored) and the
expiry date: a reliably read printed expiry that differs from the MRZ expiry is FLAG. The
expiry checked against the evaluation date is the MRZ one (check-digit verified); a printed
expiry that could not be read reliably adds no finding. A low-confidence MRZ expiry is FLAG
even if it looks long past.

**4.2 NID.** NID-01 needs a translation page even when the card itself shows English. A
translation page is recognised by its own wording ("translated", "translation", "true copy",
"authorized to translate"); notary text alone does not make a notarised photocopy of the
card its own translation. NID rules run on every NID, including one NID-ASSIGN could not
assign. NID-03 / TIN-02 count differing positions when both numbers have the same length,
and edit distance only when a digit was dropped or added.

**4.3 Birth (and every "If Bangla, must have English translation" rule).** BIRTH-03: a
different year FAILs even across New Year (31-12 vs 01-01). BIRTH-04 never FAILs: a BRN not
starting with the birth year (e.g. old 13/16-digit format) is FLAG. BIRTH-01 / TRADE-01 /
EMP-01 / DEATH-02 FAIL only a document that is in Bangla without a translation; a bilingual
(partly Bangla) document without a separate translation page is FLAG.

**2.2 and every "must belong to the father or mother" rule.** When a parent's reference
name could not be read at all (e.g. the Birth Certificate's father field), a document that
might be that parent's is FLAG ("could not be assigned with certainty"), not FAIL
("unknown person"). LANG-02 likewise FLAGs, not FAILs, when StudentRef is missing.

**4.4 / notarisation (all documents).** A seal counts as a notary stamp when its own ring
text, read by seal recognition, has a word starting with "NOTAR" or "ADVOCAT" (so misreads
such as "NOTARY PULIC" still count, but "REG NO TAREK" does not). A seal whose text says
something else (a government emblem, a Union Parishad or university seal, an apostille's
consular seal) does not count. Only a seal with no readable text can be confirmed by
"Notary Public"/"Advocate" printed next to it.

**4.5 Bank.** BANK-03 compares the solvency date with the statement that has the same
account number, but only when both numbers were read reliably; otherwise it does not pick a
statement on shaky digits and FLAGs unless some statement's date matches. Dates must be
identical (a one-day difference is FAIL, as written).

**4.8 detail.** ACAD-02 never FAILs "no transcript" (or "no certificate") while a document
whose level could not be read might be the missing partner: that is FLAG.

**4.6 Trade License.** TRADE-03: a fiscal year later than the current one (e.g. a licence
renewed early) is FLAG, not PASS.

**4.7 TIN.** *(TIN-03 approved.)* TIN-03 compares the taxpayer with the Trade License owner; when there is no
Trade License but an Employment Certificate, it compares with the employee instead.
TIN-02 treats ZXing's QR value as exact.

**4.8 Academic.**
* ACAD-01 needs the online check. Until online checks are enabled, an official link
  (https://apostille.mygov.bd/...) is FLAG ("not verified online"), a link to any other
  site or over http is FAIL ("QR invalid"), an undecodable QR is FLAG.
* *(Approved.)* ACAD-02: real submissions give each certificate and each transcript its own e-Apostille
  page, so "every e-Apostille followed by a Certificate AND a Transcript" is read as "every
  level needs both its certificate and its transcript". A missing transcript FAILs (as
  written); a missing certificate also FAILs (the pair is mandatory). An apostille not
  followed by an academic document is FLAG. No academic documents at all is FLAG (section 3
  does not list academics as required).
* *(Approved.)* ACAD-03: the rulebook only says when to PASS. Any other combination is FLAG.
* ACAD-04: name and SSC/Dakhil date-of-birth mismatches are FLAG (as written), even
  though an uncovered name mismatch elsewhere would FAIL under 5.2.

**4.9 Income Tax.** Optional: no tax documents is PASS (TAX-01) and TAX-02..04 only run
for the documents present. TAX-04 needs the online challan check; until it is enabled a
challan is FLAG ("not verified online").

**4.10 IELTS/TOPIK.** Optional: absent produces no LANG results and REQ-10 notes it.
"Within 2 years" is counted from the test date (IELTS) or issue date (TOPIK), inclusive.

**Online checks (ACAD-01, TAX-04)**, enabled with the owner's permission (2026-11-11).
The rules engine never goes online; `hklv_online` fills in each e-Apostille's and
challan's result between extraction and the rules.

* e-Apostille: the application number from the QR (only from an https link on
  apostille.mygov.bd) is looked up at `https://apostille.mygov.bd/application-details/<n>`.
  The register confirming the number -> VERIFIED (PASS); the register's "not found" answer
  -> NOT_FOUND (FAIL: QR invalid); anything else -> UNAVAILABLE (FLAG). Limitation: this
  proves the apostille exists in the official register, not that its contents match the
  scan; the record page itself refuses automated access and the engine does not try to
  get around that.
* Challan: challanverification.finance.gov.bd shows automated challans (A-challan numbers,
  `YYYY-NNNNNNNNNN`) by embedding the Finance Division's A-challan system,
  www.achallan.gov.bd, so that is the host the check calls. Found -> the website amount is
  compared with the printed amount (TAX-04 PASS/FAIL); no such challan, or a challan with a
  refund request (marked "not valid for any service"), -> NOT_FOUND (FAIL); anything else
  -> UNAVAILABLE (FLAG). Bank-counter challans need bank, branch and date on the site's form
  and are left for manual review (FLAG). No real challan has been checked yet: the sample
  set has none. The owner confirmed on 2026-11-11 that real challan numbers may be sent to
  www.achallan.gov.bd in production.
* Only those two official hosts are ever contacted, over https; the QR's own URL is never
  opened (the official URL is rebuilt from the number), and redirects elsewhere are refused.
* `scripts/run_case.py --offline` turns the checks off (ACAD-01 / TAX-04 then FLAG).

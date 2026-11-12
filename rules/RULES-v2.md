# HKLV RULES — VERSION 2 (2026-11-12)

This is the single, complete set of rules the engine applies. It merges `rulebook.md`
(Rulebook v2.5), `docs/rulebook-supplement-draft.md` and every change agreed up to
2026-11-12. Those two source files are kept unchanged as history.

**Changed from version 1:**
* Notarisation: "Notary Public" / "Advocate" text that is found counts, whatever its OCR
  confidence. Only a doubtful stamp makes the check FLAG.
* Notarisation: the notary's big red foil seal counts as the stamp, even when only part of
  it is on the page (cut off at the edge). This replaces BIRTH-02's "a red foil seal the
  layout model misses stays FLAG; colour-based seal detection is deferred".
* FRC-03: a parent who has died need not have a row. The FATHER (MOTHER) row may be missing
  when the certificate names that parent as "Late ..." and that parent's death certificate
  is in the case. *(approved)*
* New ACAD-05: every academic certificate and transcript must be notarised. *(approved)*

**Versioning.** This file is never edited to change a rule. When a new set of rules
contradicts a rule here, a new file `RULES-v3.md` (then v4, ...) is made: it holds every
rule from this version, with each contradicted rule replaced by the new one and the old
wording deleted. A new version lists what changed at its top. Older versions stay as they
are. A new rule that contradicts nothing is still added through a new version, so the
latest file is always the whole rulebook.

**System Type:** Content-driven, 3-pass architecture, online API dependent.
**Core Logic:** FAIL (hard error / forgery) > FLAG (uncertain / needs manual review) > PASS (valid).
**Status marks:** *(approved)* = approved by the owner; *(needs approval)* = engine
interpretation still awaiting review. Unmarked = rulebook text or agreed change.

---

## SECTION 0: Conventions used by every rule

* Unreadable or low-confidence values (OCR confidence below 0.90) -> FLAG, never a guess.
  Exceptions are named in the rule (BIRTH-03, BANK-02, StudentRef).
* Name matching is exact after cleanup. The same words in another order count as the same
  name. The MD / MST titles match their common spellings (MOHAMMED, MUHAMMAD, MOSAMMET ...).
  Other spelling differences need an affidavit (5.2).
* "If Bangla, must have English translation" (BIRTH-01, TRADE-01, EMP-01, DEATH-02): FAIL
  only a document that is in Bangla without a translation; a bilingual (partly Bangla)
  document without a separate translation page is FLAG. *(needs approval)*
* A translation page is recognised by its own wording ("translated", "translation", "true
  copy", "authorized to translate"); notary text alone does not make a notarised photocopy
  its own translation. When an agency stamp saying "Translation" is on every page, only the
  page carrying the translator's block ("TRUE COPY", "Translated by") is the translation.
* Notarisation (all documents): the "Notary Public" / "Advocate" text only has to be found;
  a low OCR confidence on it doesn't make it doubtful. The notary's red foil seal (a large,
  solid red disc, found by colour) counts as the stamp, whole or partly cut off at the page
  edge; a small round red logo, red text or an outline red rubber stamp does not.
  Otherwise a seal counts as a notary stamp when its own ring text has a
  word starting with "NOTAR" or "ADVOCAT" (misreads like "NOTARY PULIC" count; "REG NO TAREK"
  does not). A seal whose text says something else (government emblem, Union Parishad,
  university, consular seal) does not count. Only a seal with no readable text can be
  confirmed by "Notary Public" / "Advocate" printed next to it. *(needs approval)*
* "Must belong to the father or mother" rules: when a parent's reference name could not be
  read at all, a document that might be that parent's is FLAG ("could not be assigned with
  certainty"), not FAIL. *(needs approval)*

## SECTION 1: Ingestion & Classification (Pass 1)

The system reads all files, OCRs every page and categorises them. File names are ignored.
Any page that matches no signature is silently ignored (IGNORE-01).

1.1 Classification signatures:
* Passport: PASSPORT and MRZ (P<BGD).
* Photo: image file (.jpg, .png), or a PDF page that holds only a picture.
* Birth Certificate: Birth Registration Number OR bdris, including the old BDR Form-3.
* NID (Digital): National ID Card and MRZ (I<BGD).
* NID (Old): National ID Card but no MRZ.
* A page that only quotes an "NID No" (bank solvency letter, employer letter) is classified
  as an NID only after the bank and employment checks.
* Family Certificate (FRC): (Family Relationship Certificate OR Family Certificate) AND
  (Union Parishad OR Pourashava OR City Corporation).
* Bank Solvency: Solvency OR To Whom It May Concern OR Account Holder.
* Bank Statement: table of transactions with Date, Debit, Credit, Balance.
* Trade License: Trade License OR Trade/Profession License OR ট্রেড লাইসেন্স. A page that
  only repeats a translation agency's own "Trade Licence No." on its letterhead (even with
  an OCR letter slip in the number, e.g. "D60631") is not a trade licence; a translated
  document on such letterhead is read as what it is. *(needs approval)*
* Employment Certificate: (Employment Certificate OR Experience Certificate OR "is working"
  OR "is employed") AND an employer letterhead.
* Death Certificate: Death Registration Number OR Death Certificate OR মৃত্যু নিবন্ধন.
* TIN Certificate: Taxpayer's Identification Number OR National Board of Revenue OR NBR.
* Academic Document: Apostille (triggers the academic block).
* Income Tax - Challan: Challan Form OR চালান ফরম.
* Income Tax - Acknowledgement: Acknowledgment Receipt OR Return of Income.
* Income Tax - Certificate: Income Tax Certificate.
* IELTS/TOPIK: IELTS, Test Report Form or TOPIK, AND a field of the test form itself
  (Candidate, Test-taker, Date of Birth, Registration No, Test Report / Test Date, Score
  Report). A personal statement or checklist that only mentions "IELTS 6.5" is not a test.
* Affidavit: Affidavit, Notary Public, Same person.

## SECTION 2: Identity Anchors & Assignment (Pass 2)

2.1 The Anchors:
* StudentRef: from the Passport; MRZ name and printed name must match. Digits in the MRZ
  name are read as their look-alike letters (0->O, 1->I, 2->Z, 5->S, 6->G, 8->B), since names
  hold no digits. A reliably read MRZ name that matches confirms a printed name read with
  low confidence.
* FatherRef: the father's name on the student's Birth Certificate. Fallback: Passport
  Father's Name field, used only when no Birth Certificate carries the field at all (an
  unreadable Birth Certificate value is FLAG, not a reason to switch).
* MotherRef: the same, with the mother's name.
* Birth Certificates are the student's only. Parents are identified by NID or passport,
  never by their own birth certificate.

2.2 NID-ASSIGN: for every NID (Old or Digital), the cardholder name:
* Matches StudentRef -> Student NID. Matches FatherRef -> Father NID. Matches MotherRef ->
  Mother NID.
* Matches nobody -> FAIL ("NID belongs to an unknown person or sibling").

## SECTION 3: Required Documents

* REQ-01: no Passport -> FAIL.
* REQ-02: no Photo -> FAIL.
* REQ-03: no Birth Certificate -> FAIL.
* REQ-04: no FRC -> FAIL.
* REQ-05: no Bank Solvency OR no Bank Statement -> FAIL.
* REQ-06: no Trade License AND no Employment Certificate -> FAIL.
* REQ-07: no TIN Certificate -> FAIL.
* REQ-08: no Father NID AND no Father Death Certificate -> FAIL.
* REQ-09: no Mother NID AND no Mother Death Certificate -> FAIL.
  REQ-08/09 count only a document assigned to that parent by name; a sibling's NID does not
  count. If none is assigned but an NID or Death Certificate that could be this parent's
  could not be assigned with certainty -> FLAG (the reason is given by NID-ASSIGN). A
  document whose name clearly mismatches the parent never softens the FAIL.
* REQ-10: Income Tax, IELTS/TOPIK and Student NID are optional. Missing -> PASS.

## SECTION 4: Document-Specific Rules

4.1 PASSPORT
* PASSPORT-01 (Expiry): expiry before the current date -> FAIL; less than 12 months from the
  current date -> FAIL (exactly 12 months passes). The expiry checked is the MRZ one
  (check-digit verified); a low-confidence MRZ expiry is FLAG even if it looks long past.
  MRZ and print mismatch -> FLAG: covers the name (word order, spacing and MRZ digit slips
  ignored, as in 2.1) and a reliably read printed expiry that differs from the MRZ expiry.
  *(needs approval: interpretation details)*

4.2 NID (assigned to Father, Mother or Student; also run on an NID that could not be assigned)
* NID-01 (Translation): must have an English translation page, even when the card shows
  English. Missing -> FAIL.
* NID-02 (Notary): must be notarised (stamp / Advocate). Missing -> FAIL.
* NID-03 (Number Match): card vs translation. Exact -> PASS; 1-2 digits differ -> FLAG; 3+
  -> FAIL. Same length: count differing positions; a dropped or added digit: edit distance.

4.3 BIRTH CERTIFICATE (the student's only)
* BIRTH-01 (Format): if Bangla, must have an English translation. Missing -> FAIL.
* BIRTH-02 (Notary): must be notarised (Section 0). Missing -> FAIL.
* BIRTH-03 (DOB): PASS / FAIL against the Passport DOB. Bangla certificate with English
  translation: only the year is compared. English certificate (old BDR Form-3, new
  bilingual bdris.gov.bd): the full date must match. A different year FAILs even across New
  Year. A low-confidence date PASSes only if it equals the passport date exactly; if it
  differs -> FLAG. On the old Form-3 the filled square between month and year
  (`25 | 02 | ■ | 2002`) is skipped.
* BIRTH-04 (BRN): BRN must start with the birth year. Mismatch (e.g. old 13/16-digit
  format) -> FLAG, never FAIL.
* BIRTH-05 (Name): name must match StudentRef. Mismatch -> FAIL (this catches a parent's
  birth certificate).

4.4 FAMILY RELATIONSHIP CERTIFICATE (FRC)
* FRC-01 (Issuer): must contain Union Parishad, Pourashava or City Corporation. Missing -> FAIL.
* FRC-02 (Identity): table must have a row whose relation is SELF, HERSELF or APPLICANT,
  with a name matching StudentRef. Missing -> FAIL. An "Applicant Name:" line under the
  table counts as an APPLICANT row. *(needs approval)*
* FRC-03 (Parents): rows for FATHER and MOTHER, names matching FatherRef and MotherRef.
  Missing -> FAIL. When the layout reader returns only part of the table, the dropped
  FATHER / MOTHER cells are unreadable rows -> FLAG. *(needs approval)*
  A parent who has died may have no row: the certificate names them as "Late <name>"
  (matching FatherRef / MotherRef) and their death certificate is in the case -> that
  parent passes. *(approved)*
* Relations are matched by word: "Father (Late)", "Father's", "Self (Applicant)" and Bangla
  পিতা / মাতা / নিজ count; "Father-in-law" and "Step Mother" do not. An unknown Bangla
  relation -> FLAG.
* FRC-04 (Date): Date of Issue or Registration within 3 months of the current date. Older -> FAIL.
* FRC-05 (Notary): must contain Notary Public or Advocate AND a stamp. Missing -> FAIL.

4.5 BANK SOLVENCY & STATEMENT (BANK-01..03: one result per solvency letter)
* BANK-01 (Holder): account holder must match FatherRef or MotherRef. StudentRef or anyone
  else -> FAIL.
* BANK-02 (Account Number): solvency account number must match the statement's. Mismatch ->
  FAIL. A number of 8+ digits read with low confidence PASSes when it equals the other
  document's reliably read number digit for digit (a misread can't land on the exact
  number); otherwise low confidence -> FLAG.
* BANK-03 (Date Match): solvency date (top of letter) vs statement date (Generation Date,
  As on, Print Date) of the statement with the same account number. Dates must be identical
  (one day apart -> FAIL). The statement is chosen by number only when both numbers were
  read reliably (or there is one statement); otherwise no statement is picked on shaky
  digits, and the result is FLAG unless some statement's date matches. *(needs approval)*
* BANK-04 (Minimum Balance): not checked. PASS.

4.6 TRADE LICENSE
* TRADE-01 (Format): if Bangla, must have an English translation. Missing -> FAIL.
* TRADE-02 (Notary): must be notarised. Missing -> FAIL.
* TRADE-03 (Fiscal Year): must be the current FY (July-June). Older -> FAIL. Later (renewed
  early) -> FLAG. *(needs approval)*
* TRADE-04 (Owner): owner must match FatherRef or MotherRef. Student -> FAIL.

4.6b EMPLOYMENT CERTIFICATE (instead of a Trade License) *(needs approval)*
* EMP-01 (Format): if Bangla, must have an English translation. Missing -> FAIL.
* EMP-02 (Notary): Notary Public / Advocate text AND a stamp. Missing -> FAIL.
* EMP-03 (Date): issue date within 3 months of the current date. Older -> FAIL.
* EMP-04 (Current): must state the person is employed now. Experience or release letter -> FAIL.
* EMP-05 (Employee): employee must match FatherRef or MotherRef. Student or anyone else -> FAIL.

4.7 TIN CERTIFICATE
* TIN-01 (QR): decode the QR. Decoding fails -> FLAG.
* TIN-02 (Number Match): printed TIN vs QR TIN (QR value treated as exact). 1-2 digits
  differ -> FLAG; 3+ -> FAIL. Counting as in NID-03.
* TIN-03 (Name Match): taxpayer name must match the Trade License owner; with no Trade
  License, the Employment Certificate employee. Mismatch -> FAIL. *(approved)*

4.8 ACADEMIC CERTIFICATES
* ACAD-01 (e-Apostille): verify the QR online (see Section 7). Register confirms -> PASS;
  register says not found, or a link to any other site or over http -> FAIL (QR invalid);
  internet fails or undecodable QR -> FLAG.
* ACAD-02 (Mandatory Pairs): every level needs both its certificate and its transcript.
  Missing transcript or certificate -> FAIL, except FLAG while a document whose level
  couldn't be read might be the missing partner. An apostille not followed by an academic
  document -> FLAG. No academic documents at all -> FLAG. *(approved)*
* ACAD-03 (Equivalency): valid tracks SSC + HSC, SSC + Alim, Dakhil + Alim, SSC + Diploma ->
  PASS. Any other combination -> FLAG. *(approved)*
* ACAD-04 (Name/DOB): names must match StudentRef; SSC/Dakhil DOB must match the Passport
  DOB. Mismatch -> FLAG.
* ACAD-05 (Notary): every academic certificate and transcript must be notarised (Section 0):
  the notary's red seal AND "Notary Public" / "Advocate". Missing -> FAIL; can't be
  confirmed -> FLAG. The e-Apostille page itself needs no notarisation. *(approved)*

4.9 INCOME TAX (optional)
* TAX-01 (Presence): no Income Tax pages -> PASS. TAX-03..04 run only for documents present.
* TAX-02: removed (2026-11-12). The challan is judged by TAX-04 only.
* TAX-03 (Wealth Limit): if an Acknowledgment is present, Total Income Shown must be
  >= 5,000,000 BDT. Less -> FLAG.
* TAX-04 (Challan Verification): challan number read from the QR first, else the printed
  text; printed amount from "Total Amount", never the line under "Amount in words". Checked
  online (Section 7): website amount = printed amount -> PASS; mismatch -> FAIL; refunded
  challan ("not valid for any service") -> FAIL; no such challan -> FLAG (a misread number
  looks the same); internet fails -> FLAG. Bank-counter challans -> FLAG (manual review).
  QR codes on the Income Tax Certificate and Acknowledgment are ignored.

4.10 IELTS / TOPIK (optional; absent -> no LANG results, REQ-10 notes it)
* LANG-01 (Expiry): within 2 years of the test date (IELTS) or issue date (TOPIK),
  inclusive. Expired -> FAIL.
* LANG-02 (Name/DOB): must match StudentRef. Mismatch -> FAIL (unless affidavit). StudentRef
  missing -> FLAG.

4.11 DEATH CERTIFICATE (replaces a parent's NID) *(needs approval)*
* DEATH-01 (Assignment): deceased must match FatherRef or MotherRef. Student or anyone else
  -> FAIL. Two certificates for the same parent -> FLAG.
* DEATH-02 (Format): if Bangla, must have an English translation. Missing -> FAIL.
* DEATH-03 (Notary): must be notarised. Missing -> FAIL.
* DEATH-04 (Date): date of death readable and not after the current date. Otherwise -> FLAG.
* DEATH-05 (Consistency): no financial document may present the deceased parent as a living
  sponsor. Employment Certificate for them issued after the date of death -> FAIL. Any other
  Employment Certificate, Trade License or TIN in their name -> FLAG.

## SECTION 5: Global Cross-Checks

5.1 The Financial Chain (TIN and Trade License / Employment Certificate; bank excluded)
* CHAIN-01: deleted (2026-11-12); it was the same check as TIN-03.
* CHAIN-02: TIN and the income document must belong to the same parent (TIN=Father,
  Trade=Father -> PASS; TIN=Father, Trade or Employment=Mother -> FAIL). A link that
  reliably matches no family member -> FAIL.
* CHAIN-03: TIN in the StudentRef name -> FAIL. (The income document being the student's is
  TRADE-04 / EMP-05's job.)
* Both a Trade License and an Employment Certificate submitted -> FLAG (reviewer picks which
  one forms the chain). One link unreadable or duplicated -> FLAG, but a link reliably in the
  student's name still FAILs.

5.2 Affidavit Coverage
* On a name mismatch (e.g. a spelling difference) the engine checks the Affidavit.
* Affidavit notarised, explicitly states both spellings are the "same person", and matches
  the student / parent -> PASS.
* No Affidavit covers the mismatch -> FAIL.

## SECTION 6: Final Verdict

1. Any rule FAIL -> overall FAIL.
2. No FAIL but any FLAG -> overall FLAG (needs manual review).
3. Otherwise PASS.
* An empty list of results -> FLAG (nothing was checked).
* Until every rule is implemented, an `ENGINE-COVERAGE` FLAG names the unchecked rules, so
  no case can PASS by accident.

## SECTION 7: Online Checks (ACAD-01, TAX-04)

Enabled with the owner's permission (2026-11-11). The rules engine never goes online;
`hklv_online` fills in the results between extraction and the rules.
* e-Apostille: the application number from the QR (only from an https link on
  apostille.mygov.bd) is looked up at `https://apostille.mygov.bd/application-details/<n>`.
  Confirmed -> VERIFIED (PASS); "not found" -> NOT_FOUND (FAIL); anything else ->
  UNAVAILABLE (FLAG). This proves the apostille exists in the register, not that the scan
  matches it.
* Challan: automated challans (`YYYY-NNNNNNNNNN`) are checked at www.achallan.gov.bd, the
  system challanverification.finance.gov.bd embeds. The owner confirmed (2026-11-11) that
  real challan numbers may be sent there.
* Only those two official hosts are contacted, over https; the QR's own URL is never opened
  (the official URL is rebuilt from the number) and redirects elsewhere are refused.
* `scripts/run_case.py --offline` turns the checks off (ACAD-01 / TAX-04 then FLAG).

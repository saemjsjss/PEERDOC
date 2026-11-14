# HKLV RULES — VERSION 13 (2026-11-14)

HKLV (Hangeul Korean Language and Visa) checks each student's documents before it applies
for the student's admission and visa in South Korea. The engine reads every page of one
student's case and gives a verdict for HKLV staff to act on. A FLAG (a person reviews it)
is always preferred to a wrong PASS or a wrong FAIL.
**Accepted limits:** the sponsor's balance and ability to pay are not checked (BANK-04);
the challan check proves that a challan exists, not that it was paid for this student
(TAX-04); the OCR confidence thresholds (0.90, and 0.85 in STAMP-01) are not
calibrated against measured error rates.

Every rule ID here is implemented in `src/hklv_rules` (ENGINE-COVERAGE, Section 6). How pages are read, classified and grouped is in
`docs/pass1-extraction.md`; this file says what makes a case valid.

**Changed from version 12:**
* Trade License signature: the English title (Trade License, Trade/Profession License,
  Professional Licence) counts only on a short line of its own (a title or a label, at
  most 8 words), not inside a sentence: a personal statement saying "my business under a
  valid trade license" is not a trade licence. *(approved, 2026-11-14)*

**Versioning.** This file is never edited to change a rule. Every change, even a new rule
that contradicts nothing, makes a new complete file (`RULES-v14.md`, ...) that lists its
changes at the top; older versions stay as they are. A deleted rule keeps a one-line
entry so that its ID is never reused.

**Passes.** Pass 1 reads and classifies every page (Section 1). Pass 2 sets the identity
anchors (Section 2). The online checks (Section 7) run next. Pass 3 applies the rules
(Sections 3-5) and gives the verdict (Section 6); it never goes online.
**Outcomes:** FAIL (hard error or forgery) > FLAG (uncertain, needs manual review) > PASS.
*(approved)* marks a rule or change the owner approved.

---

## SECTION 0: Definitions used by every rule

* **Check date:** the case's evaluation date (default: the upload day). Every date rule
  uses it.
* **Within N months:** on or after the same day N months before the check date (the last
  day of the month when that day does not exist: 31 May - 3 months = 28 Feb), so the end
  day counts. "At least N months after" works the same way forward. A date after the check
  date is a misread -> FLAG.
* **Reliable:** read with OCR confidence of 0.90 or more ("reliably read", "with
  certainty"). A value that is unreliable, or not found, is FLAG, never a guess. Only these
  rules depart from that, each for the reason given:
  * Confirmed by a second reading: a low-confidence value counts when it exactly equals an
    independent reading: the passport MRZ name (StudentRef), the passport date of birth
    (BIRTH-03), or another document's number of 8 or more digits, digit for digit (NID-03,
    BANK-02).
  * Presence decides: only whether something is found matters (the notary text below,
    BANK-05; TRADE-03, where no validity date is a FAIL).
  * Not checked when unsure: ACAD-06 reports PASS with the reason "not checked".
  * Own threshold: STAMP-01 uses 0.85.
* **Name match:** two names match when they are the same after cleanup, or the same words
  in another order. Cleanup ignores case, punctuation and spaces, drops a parentage suffix
  ("S/O ...", "D/O ...", "W/O ...", "C/O ..."), and treats the spellings of MD (MOHAMMAD,
  MOHAMMED, MUHAMMAD ...) and of MST (MOSAMMAT, MOSAMMET ...) as one title. A title is never
  dropped: "MST RAHIMA" and "RAHIMA" differ. Any other difference needs an affidavit (5.2).
  A reference name that could not be established matches nothing for certain -> FLAG.
* **Assigned by name:** a document's name is matched against the reference names of the
  people the rule allows (StudentRef, FatherRef, MotherRef; Section 2). A name matching
  exactly one allowed person -> PASS (assigned to them). Matching only a person who is
  not allowed (the student on a parent's document) -> FAIL. Matching nobody -> FAIL, but FLAG
  when an allowed person's reference name could not be read (the document may be theirs).
  Unreliable or not found, or matching two people -> FLAG ("could not be assigned with
  certainty"). An exact match wins over one bridged by an affidavit. Two NIDs, or two
  Death Certificates, assigned to the same person -> FLAG.
* **Translation:** a document "needs an English translation" FAILs only when it is in
  Bangla with no translation page. A bilingual (partly Bangla) document with no separate
  translation page is FLAG (BIRTH-01 and NID-01 name their exceptions). A translation page is known by
  its own wording ("translated", "translation", "true copy", "authorized to translate");
  notary text alone does not make a page a translation. When an agency stamp saying
  "Translation" is on every page, only the page with the translator's block ("TRUE COPY",
  "Translated by") is the translation. *(approved)*
* **Notarised:** the "Notary Public" or "Advocate" text AND a notary stamp are both on the
  document. The text only has to be found (presence decides). A stamp is the notary's red
  foil seal (a large solid red disc, whole or cut off at the page edge), or a seal whose own
  ring text has a word starting "NOTAR" or "ADVOCAT" (OCR slips inside that word count). A
  small red logo, red text, an outline rubber stamp, or a seal whose text names something
  else (a government emblem, Union Parishad, university or consulate) is not a notary
  stamp. A seal with no readable text counts only when "Notary Public" / "Advocate" is
  printed next to it. Text or stamp reliably absent -> FAIL; either one not confirmed ->
  FLAG. *(approved)*
* **Missing documents:** a rule about one document type gives no result when no such
  document is in the case; Section 3 FAILs the missing document once.

## SECTION 1: Ingestion & Classification (Pass 1)

Every page is OCR-read and given one document type by its signature below; file names are
ignored. The order in which signatures are tried is in `docs/pass1-extraction.md`
("Classification order"). Words in quotes are OCR keywords and keep the document's own
spelling (License / Licence, Acknowledgment / Acknowledgement).
* IGNORE-01: a page that matches no signature is ignored.

1.1 Classification signatures:
* Passport: a passport MRZ (P<).
* Photo: an image file (.jpg, .png) with little or no text, or a PDF page that holds only a
  picture.
* Birth Certificate: Birth Registration Number OR bdris, including the old BDR Form-3.
* NID (Digital): an ID-card MRZ (I<).
* NID (Old): National ID Card without MRZ. A page that only quotes an "NID No" (a bank or
  employer letter) is an NID only when it is not a Bank Solvency or Employment Certificate.
* Family Certificate (FRC): (Family Relationship Certificate OR Family Certificate) AND
  (Union Parishad OR Pourashava OR City Corporation).
* Bank Solvency: Solvency OR Account Holder, OR (To Whom It May Concern AND bank AND
  account words).
* Bank Statement: a transaction table with Date, Debit, Credit and Balance.
* Trade License: Trade License OR Trade/Profession License OR Professional Licence, on a
  line of at most 8 words (a title or a label, not a sentence), OR Name of Licence(s) Holder
  OR ট্রেড লাইসেন্স OR the licence's own verification QR. A page that only repeats a translation
  agency's own "Trade Licence No." on its letterhead is not a trade licence; a translated
  document on such letterhead is read as what it is. *(approved)*
* Employment Certificate: Employment Certificate OR Experience Certificate OR "is working"
  OR "is employed" OR "is serving". Without one of the two titles, a page that also has
  academic-certificate words is not an Employment Certificate.
* Death Certificate: Death Registration Number OR Death Certificate OR মৃত্যু নিবন্ধন.
* TIN Certificate: Taxpayer's Identification Number OR TIN Certificate OR ((National Board
  of Revenue OR NBR) AND "TIN").
* Academic Document: an Apostille page starts the academic block, which runs until the
  first page that is neither an academic certificate nor a transcript; certificates and
  transcripts count only inside it.
* Income Tax - Challan: Challan Form OR চালান ফরম.
* Income Tax - Acknowledgment: Acknowledgment Receipt OR Return of Income.
* Income Tax - Certificate: Income Tax Certificate.
* IELTS/TOPIK: IELTS, Test Report Form or TOPIK, AND a field of the test form itself
  (Candidate, Test-taker, Date of Birth, Registration No, Test Report / Test Date, Score
  Report). A personal statement or checklist that only mentions "IELTS 6.5" is not a test.
* Affidavit: Affidavit OR Same person OR হলফনামা. "Notary Public" alone is not a signature.

## SECTION 2: Identity Anchors & Assignment (Pass 2)

2.1 The Anchors:
* StudentRef: from the Passport; the MRZ name and the printed name must match (digits that
  OCR puts in the MRZ name are read as their look-alike letters). A reliable MRZ name that
  matches confirms a printed name read with low confidence.
* FatherRef: the father's name on the student's Birth Certificate. Only when no Birth
  Certificate has that field at all is the Passport's Father's Name used (an unreliable
  Birth Certificate value is FLAG, not a reason to switch).
* MotherRef: the same, with the mother's name.
* Birth Certificates are the student's only. A parent is identified by their NID or Death
  Certificate, never by their own birth certificate.

2.2 NID-ASSIGN: every NID (Old or Digital) is assigned by name (Section 0) to the student,
the father or the mother (reason when it matches nobody: "unknown person or sibling").

2.3 The student's own employment letter: an Employment Certificate whose employee reliably
matches StudentRef, and neither parent, is the student's CV document (past jobs, ECA:
extra-curricular activities). It is ignored like an IGNORE-01 page: it gets no EMP
results, does not count for REQ-06 and is not part of the financial chain. When the name
also matches a parent, or is not reliable, the letter is kept and EMP-05 judges it.
*(approved)*

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
  REQ-08/09 count only a document assigned to that parent (NID-ASSIGN, DEATH-01); a
  sibling's NID does not count. If none is assigned but one could not be assigned with
  certainty -> FLAG. A document whose name reliably mismatches the parent never softens
  the FAIL.
* REQ-10: IELTS/TOPIK and the Student NID are optional: missing -> PASS. Income Tax is
  optional too (TAX-01).

## SECTION 4: Document-Specific Rules

4.1 PASSPORT
* PASSPORT-01 (Expiry): the MRZ expiry (check-digit verified) must be at least 12 months
  after the check date; earlier, or already past -> FAIL. MRZ and printed page disagree ->
  FLAG: the names do not match (Section 0, with MRZ digits read as in 2.1), or a reliable
  printed expiry differs from the MRZ expiry. *(approved)*

4.2 NID (assigned to the father, mother or student, and also an NID that could not be assigned)
* NID-01 (Translation): must have an English translation page, even when the card shows
  English. Missing -> FAIL.
* NID-02 (Notary): must be notarised (Section 0).
* NID-03 (Number Match): card number vs translation number. Equal -> PASS; 1-2 digits
  differ -> FLAG; 3 or more -> FAIL. Same length: count the differing positions; a dropped
  or added digit: edit distance. A low-confidence number is confirmed as in Section 0.
  *(approved)*

4.3 BIRTH CERTIFICATE (the student's only)
* BIRTH-01 (Translation): needs an English translation (Section 0). A bilingual certificate
  (Bangla and English on one page, e.g. BDRIS) needs no translation page when its English
  side gives the child's name, date of birth, father's name and mother's name; any of them
  not reliable -> FLAG. *(approved)*
* BIRTH-02 (Notary): must be notarised (Section 0).
* BIRTH-03 (DOB): compared with the Passport date of birth. A Bangla certificate with an
  English translation: the year only. An English certificate (old BDR Form-3, bilingual
  BDRIS): the full date. A different year FAILs even when the dates are days apart
  (31-12-2001 vs 01-01-2002). A low-confidence date PASSes only if it equals the passport
  date exactly; otherwise -> FLAG.
* BIRTH-04 (BRN): the Birth Registration Number must start with the birth year. Mismatch
  (e.g. the old 13- or 16-digit format) -> FLAG, never FAIL.
* BIRTH-05 (Name): the name must match StudentRef. Mismatch -> FAIL (this catches a
  parent's birth certificate).

4.4 FAMILY RELATIONSHIP CERTIFICATE (FRC)
In FRC-02 and FRC-03, relations are matched by word: "Father (Late)", "Father's", "Self
(Applicant)" and Bangla পিতা / মাতা / নিজ count; "Father-in-law" and "Step Mother" do not. An
unknown Bangla relation -> FLAG.
* FRC-01 (Issuer): the issuer must be a Union Parishad, Pourashava or City Corporation.
  Reliably something else -> FAIL.
* FRC-02 (Identity): the table must have a row whose relation is SELF or a word for the
  applicant themself (HIMSELF, HERSELF, MYSELF, ONESELF, APPLICANT, STUDENT, CANDIDATE),
  with a name matching StudentRef. An "Applicant Name:" line under the table counts as an
  APPLICANT row. No such row in a reliably read table -> FAIL. *(approved)*
* FRC-03 (Parents): rows for FATHER and MOTHER whose names match FatherRef and MotherRef.
  No such row in a reliably read table -> FAIL; a row the reader could not return is
  unreliable -> FLAG. A parent
  who has died may have no row: the certificate names them "Late <name>" (matching their
  reference name) and their Death Certificate is assigned to them (DEATH-01) -> that
  parent passes. *(approved)* A parent with no row whose Death Certificate is assigned to
  them, but no "Late <name>" read -> FLAG.
* FRC-04 (Date): the Date of Issue or Registration must be within 3 months. Older -> FAIL.
* FRC-05 (Notary): must be notarised (Section 0).

4.5 BANK SOLVENCY & STATEMENT (BANK-01..03 and BANK-05: one result per solvency letter)
* BANK-01 (Holder): the account holder is assigned by name (Section 0) to the father or
  mother.
* BANK-02 (Account Number): the solvency's account number must equal the statement's.
  Mismatch -> FAIL. A low-confidence number is confirmed as in Section 0 (a misread is
  very unlikely to land on the exact number). *(approved)*
* BANK-03 (Date Match): the solvency letter date (top of the letter) must be identical to
  the date of the statement with the same account number (Generation Date, As on, Print
  Date); one day apart -> FAIL. The statement is picked by number only when both numbers
  are reliable, or there is only one statement. Otherwise every statement whose number is
  not reliably different is compared: a date match -> PASS, no match -> FLAG, never FAIL.
  *(approved)*
* BANK-04 (Minimum Balance): always PASS, with the reason "not checked".
* BANK-05 (Currencies): the solvency letter must state the balance in USD and in BDT,
  written next to the currency ("USD 19,338.09", "BDT. 2,407,592.52") or in a column headed
  by it ("Balance (USD)"). An exchange rate ("1 USD = 123.70") is not an amount, and the
  figures are not checked. Either currency missing -> FAIL. *(approved)*

4.6 TRADE LICENSE
* TRADE-01 (Translation): needs an English translation (Section 0).
* TRADE-02 (Notary): must be notarised (Section 0).
* TRADE-03 (Validity): the fiscal year runs 1 July - 30 June. The licence PASSes if, on the
  check date, it is valid until at least the 30 June that ends the current fiscal year
  (from a "Valid up to" date, or the fiscal year printed: 2026-2027 = valid until
  30-06-2027), OR it was issued on or after the 1 July that started that fiscal year.
  Checked in January 2027: valid until 30-06-2027, or issued since 01-07-2026. Neither ->
  FAIL, also when no such date is found. A date that would pass but is unreliable -> FLAG.
  An issue date after the check date -> FLAG (a misread).
  A renewal page listing several years counts the latest. *(approved)*
* TRADE-04 (Owner): the owner is assigned by name (Section 0) to the father or mother.

4.6b EMPLOYMENT CERTIFICATE (instead of a Trade License) *(approved)*
* EMP-01 (Translation): needs an English translation (Section 0).
* EMP-02 (Notary): must be notarised (Section 0).
* EMP-03 (Date): the issue date must be within 3 months. Older -> FAIL.
* EMP-04 (Current): must state that the person is employed now. An experience or release
  letter -> FAIL.
* EMP-05 (Employee): the employee is assigned by name (Section 0) to the father or mother.
  The student's own CV letter never reaches this rule (2.3).

4.7 TIN CERTIFICATE
* TIN-01 (QR): the QR must decode. It doesn't -> FLAG.
* TIN-02 (Number Match): the printed TIN vs the QR TIN (the QR value is exact). 1-2 digits
  differ -> FLAG; 3 or more -> FAIL. Counted as in NID-03.
* TIN-03 (Taxpayer): the taxpayer is assigned by name (Section 0) to the father or mother.
  *(approved)*

4.8 ACADEMIC CERTIFICATES (SSC / HSC: secondary / higher secondary school certificates;
Dakhil / Alim: their madrasah equivalents)
* ACAD-01 (e-Apostille): the apostille is looked up in the official register (Section 7)
  and the register's own copy must be the student's. *(approved)*
  * Number: from the QR; when the QR can't be decoded, from the "8. Nº" line printed on
    the page. A QR that links to another site or uses http -> FAIL. Neither read -> FLAG.
    QR number and a reliable printed No. that differ: the QR's number is looked up as
    usual; a FAIL from the register or owner check stands, any other result -> FLAG.
  * Register: says not found -> FAIL (FLAG when only the printed No. was looked up: a
    misread number looks the same). The internet fails -> FLAG.
  * Owner: the register's copy of the document is read like a submitted one. It must hold
    the kind (certificate or transcript) and level of the document that follows the
    apostille, and be in the student's name (StudentRef, Section 0). A register copy in
    another name, of another level, or with a different reliable board registration number
    than the document -> FAIL. A register copy that could not be downloaded or read, or a
    name that is not reliable -> FLAG; a copy read only in part never gives the "other
    level" FAIL (the missing page may be the one). All match -> PASS.
* ACAD-02 (Mandatory Pairs): every level needs both its certificate and its transcript.
  One missing -> FAIL, but FLAG while a document whose level is not reliable might be the
  missing one. An apostille not followed by an academic document -> FLAG. No academic
  documents at all -> FLAG. *(approved)*
* ACAD-03 (Equivalency): SSC + HSC, SSC + Alim, Dakhil + Alim or SSC + Diploma -> PASS. Any
  other combination -> FLAG. *(approved)*
* ACAD-04 (Name/DOB): the names must match StudentRef, and the SSC/Dakhil date of birth the
  Passport's. Mismatch -> FLAG.
* ACAD-05 (Notary): every academic certificate and transcript must be notarised (Section
  0). The e-Apostille page itself needs no notarisation. *(approved)*
* ACAD-06 (Registration): the SSC and HSC carry the same board registration number; only
  the session after "/" differs (1910534278/2020-21 and 1910534278/2022-23). Two reliable
  numbers that differ -> FLAG. A number that is unreliable or not found is not checked
  (Section 0). Runs only when both an SSC and an HSC document are present. *(approved)*

4.9 INCOME TAX (optional)
* TAX-01 (Presence): no Income Tax pages -> PASS. TAX-03 and TAX-04 run only for the
  documents present.
* TAX-02: deleted (2026-11-12); the challan is judged by TAX-04 only.
* TAX-03 (Income Shown): when an Acknowledgment is present, its Total Income Shown must be
  at least 5,000,000 BDT. Less -> FLAG.
* TAX-04 (Challan Verification): the challan number comes from the QR, else the printed
  text; the amount from "Total Amount". It is checked online (Section 7): the website
  amount equals the printed amount -> PASS; they differ -> FAIL; a refunded challan ("not
  valid for any service") -> FAIL; no such challan -> FLAG (a misread number looks the
  same); the internet fails -> FLAG. A bank-counter challan (paid at a bank, without an
  automated `YYYY-NNNNNNNNNN` number) -> FLAG. QR codes on the Income Tax Certificate and
  Acknowledgment are ignored.

4.10 IELTS / TOPIK (optional; absent -> no LANG results)
* LANG-01 (Expiry): the test date (IELTS) or issue date (TOPIK) must be within 24 months.
  Older -> FAIL.
* LANG-02 (Name/DOB): must match StudentRef and the Passport date of birth. Mismatch -> FAIL
  (5.2 applies). StudentRef missing -> FLAG.

4.11 DEATH CERTIFICATE (replaces a parent's NID) *(approved)*
* DEATH-01 (Assignment): the deceased is assigned by name (Section 0) to the father or
  mother.
* DEATH-02 (Translation): needs an English translation (Section 0).
* DEATH-03 (Notary): must be notarised (Section 0).
* DEATH-04 (Date): the date of death must be reliable and not after the check date.
  Otherwise -> FLAG.
* DEATH-05 (Consistency): no financial document may present the deceased parent as a living
  sponsor. An Employment Certificate for them issued after the date of death -> FAIL. Any
  other Employment Certificate, Trade License or TIN in their name -> FLAG.

4.12 NOTARY AND TRANSLATION DATES *(approved)*
* STAMP-01 (Date): on every document, each notary date (on or beside the notary's stamp:
  "09 JUN 2026", "Date: 23/06/2026") and each translator date (beside "Translated by")
  must be within 3 months. Older -> FAIL. A date read below 0.85 confidence -> FLAG. Translation and notarisation may be on different days.
  Document dates printed near the notary block (publication date, issue date, a birth date
  in a table) are not notary dates.

## SECTION 5: Global Cross-Checks

5.1 The Financial Chain
* CHAIN-01: deleted (2026-11-12); it repeated TIN-03.
* CHAIN-02 (Same Parent): the TIN Certificate, the income document (Trade License or
  Employment Certificate) and every Bank Solvency must belong to the same parent. Only
  documents assigned to a parent by their own rule (TIN-03, TRADE-04, EMP-05, BANK-01) are
  compared; when one of the three has none, CHAIN-02 gives no result (the document's own
  rule, or REQ-05 / REQ-06 / REQ-07, reports it). One parent has both a TIN and an income
  document and every compared account holder is that parent -> PASS; an account holder is
  the other parent -> FAIL. No parent has both (TIN = father, income = mother) -> FAIL. Both
  parents have both: every compared account holder the same parent -> PASS, otherwise ->
  FLAG (the reviewer picks). *(approved)*
* CHAIN-03: merged into TIN-03 (version 9).
* CHAIN-04: merged into BANK-01 and CHAIN-02 (version 9).

5.2 Affidavit Coverage
* On a name mismatch (e.g. a spelling difference) the engine looks for an Affidavit.
* The Affidavit is notarised (Section 0), states that both spellings are the "same person",
  and matches the student or parent -> the names match.
* No Affidavit covers the mismatch -> the rule's own mismatch outcome stands (FAIL, or FLAG
  where the rule says FLAG, as ACAD-04).

## SECTION 6: Final Verdict

1. Any rule FAIL -> overall FAIL.
2. No FAIL but any FLAG -> overall FLAG (needs manual review).
3. Otherwise PASS.
* An empty list of results -> FLAG (nothing was checked).
* ENGINE-COVERAGE: a rule listed here but not implemented is named in a FLAG, so no case
  can PASS by accident.

## SECTION 7: Online Checks (ACAD-01, TAX-04)

Enabled with the owner's permission (2026-11-11). `hklv_online` runs after Pass 1 and
before Pass 3, and its results feed ACAD-01 and TAX-04.
* e-Apostille: the application number (from an https QR link on apostille.mygov.bd, or
  the printed No.) is looked up at `https://apostille.mygov.bd/application-details/<n>`.
  For a confirmed number, the register's details are fetched from
  `https://api.apostille.mygov.bd/api/v1/application-details/<n>` (the lookup behind
  mofa-servicedirectory.apostille.mygov.bd): the apostille date, the titles of the
  apostilled documents and their page images. The images are downloaded at once (their
  links expire), read by OCR and not stored.
* Challan: automated challans (`YYYY-NNNNNNNNNN`) are checked at www.achallan.gov.bd, the
  system that challanverification.finance.gov.bd embeds; the answer gives TAX-04's outcome. The owner confirmed (2026-11-11)
  that real challan numbers may be sent there.
* Only those official hosts (apostille.mygov.bd, api.apostille.mygov.bd,
  www.achallan.gov.bd) are contacted, over https; register page images are opened only
  from api.apostille.mygov.bd; the QR's own URL is never
  opened (the official URL is rebuilt from the number) and redirects elsewhere are refused.
* `scripts/run_case.py --offline` turns the checks off (ACAD-01 and TAX-04 then FLAG).

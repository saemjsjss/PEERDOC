# FINAL DETERMINISTIC RULEBOOK (v2.5)
**System Type:** Content-Driven, 3-Pass Architecture, Online API Dependent.
**Core Logic:** FAIL (Hard error/Forgery) > FLAG (Uncertain/Needs manual review) > PASS (Valid).

## SECTION 1: Ingestion & Classification (Pass 1)
The system reads all files, OCRs every page, and categorizes them. File names are ignored. Any page that does not match these signatures is silently ignored (Rule IGNORE-01).

1.1 Classification Signatures (Keywords to trigger the document type):
*   Passport: PASSPORT and MRZ (P<BGD).
*   Photo: Image file (.jpg, .png). (No text needed).
*   Birth Certificate: Birth Registration Number OR bdris.
*   NID (Digital): National ID Card and MRZ (I<BGD).
*   NID (Old): National ID Card but NO MRZ.
*   Family Certificate (FRC): (Family Relationship Certificate OR Family Certificate) AND (Union Parishad OR Pourashava OR City Corporation).
*   Bank Solvency: Solvency OR To Whom It May Concern OR Account Holder.
*   Bank Statement: Table of transactions with Date, Debit, Credit, Balance.
*   Trade License: Trade License OR Trade/Profession License OR ট্রেড লাইসেন্স.
*   TIN Certificate: Taxpayer's Identification Number OR National Board of Revenue OR NBR.
*   Academic Document: Apostille (triggers the academic block).
*   Income Tax - Challan: Challan Form OR চালান ফরম.
*   Income Tax - Acknowledgement: Acknowledgment Receipt OR Return of Income.
*   Income Tax - Certificate: Income Tax Certificate.
*   IELTS/TOPIK: IELTS, Test Report Form, or TOPIK.
*   Affidavit: Affidavit, Notary Public, Same person.

## SECTION 2: Identity Anchors & Assignment (Pass 2)
Before applying rules, the system establishes the truth.

2.1 The Anchors:
*   StudentRef: Extracted from the Passport (MRZ Name and Printed Name must match).
*   FatherRef: Extracted from Birth Certificate. Fallback: Passport Father's Name field.
*   MotherRef: Extracted from Birth Certificate. Fallback: Passport Mother's Name field.

2.2 NID Auto-Assignment:
For every NID found (Old or Digital), extract the Cardholder Name:
*   Matches StudentRef -> Assigned to Student NID.
*   Matches FatherRef -> Assigned to Father NID.
*   Matches MotherRef -> Assigned to Mother NID.
*   Matches Nobody -> FAIL ("NID belongs to an unknown person or sibling").

## SECTION 3: Required Documents (Missing Checks)
*   REQ-01: If no Passport -> FAIL.
*   REQ-02: If no Photo -> FAIL.
*   REQ-03: If no Birth Certificate -> FAIL.
*   REQ-04: If no FRC -> FAIL.
*   REQ-05: If no Bank Solvency OR no Bank Statement -> FAIL.
*   REQ-06: If no Trade License OR Employment Certificate -> FAIL.
*   REQ-07: If no TIN Certificate -> FAIL.
*   REQ-08: If no Father NID AND no Father Death Certificate -> FAIL.
*   REQ-09: If no Mother NID AND no Mother Death Certificate -> FAIL.
*   REQ-10: Income Tax and Student NID are Optional. If missing -> PASS.

## SECTION 4: Document-Specific Rules

4.1 PASSPORT
*   PASSPORT-01 (Expiry): If Expiry < Current Date -> FAIL. If Expiry < 12 months from Current Date -> FAIL. If MRZ and Print mismatch -> FLAG.

4.2 NID (Assigned to Father, Mother, or Student)
*   NID-01 (Translation): Must have an English translation page. If missing -> FAIL.
*   NID-02 (Notary): Must be notarized (Stamp/Advocate). If missing -> FAIL.
*   NID-03 (Number Match): NID number on card vs translation. Exact match -> PASS. 1-2 digits diff -> FLAG. 3+ digits diff -> FAIL.

4.3 BIRTH CERTIFICATE
*   BIRTH-01 (Format): If Bangla, must have English translation. If missing -> FAIL.
*   BIRTH-02 (Notary): Must be notarized. If missing -> FAIL.
*   BIRTH-03 (DOB): Must match Passport DOB. Year differs -> FAIL. Day/month differs -> FLAG.
*   BIRTH-04 (BRN): BRN must start with birth year. If mismatch -> FLAG.

4.4 FAMILY RELATIONSHIP CERTIFICATE (FRC)
*   FRC-01 (Issuer): Must contain Union Parishad, Pourashava, or City Corporation. If missing -> FAIL.
*   FRC-02 (Identity): Table must have a row where relation is SELF, HERSELF, or APPLICANT. Name must match StudentRef. If missing -> FAIL.
*   FRC-03 (Parents): Table must contain rows for FATHER and MOTHER. Names must match FatherRef and MotherRef. If missing -> FAIL.
*   FRC-04 (Date): Date of Issue or Registration must be within 3 months of current date. If older -> FAIL.
*   FRC-05 (Notary): Must contain Notary Public or Advocate AND a stamp. If missing -> FAIL.

4.5 BANK SOLVENCY & STATEMENT
*   BANK-01 (Holder): Solvency Account Holder must match FatherRef or MotherRef. If StudentRef -> FAIL.
*   BANK-02 (Account Number): The Account Number on the Solvency must match the Account Number on the Statement. If mismatch -> FAIL.
*   BANK-03 (Date Match): Extract Solvency Date (top of letter) and Statement Date (Generation Date, As on, Print Date). Dates must match exactly. If mismatch -> FAIL.
*   BANK-04 (Minimum Balance): Do not check. PASS.

4.6 TRADE LICENSE & EMPLOYMENT
*   TRADE-01 (Format): If Bangla, must have English translation. If missing -> FAIL.
*   TRADE-02 (Notary): Must be notarized. If missing -> FAIL.
*   TRADE-03 (Fiscal Year): Must be current FY (July-June). If older -> FAIL.
*   TRADE-04 (Owner): Extract owner. Must match FatherRef or MotherRef. If Student -> FAIL.

4.7 TIN CERTIFICATE
*   TIN-01 (QR): Decode QR. If decoding fails -> FLAG.
*   TIN-02 (Number Match): Printed TIN vs QR TIN. 1-2 digits diff -> FLAG. 3+ digits diff -> FAIL.
*   TIN-03 (Name Match): Taxpayer Name must match Trade License Owner. If mismatch -> FAIL.

4.8 ACADEMIC CERTIFICATES
*   ACAD-01 (e-Apostille): Internet required. Verify the QR link. If internet fails -> FLAG. If QR is invalid -> FAIL.
*   ACAD-02 (Mandatory Pairs): Every e-Apostille MUST be followed by a Certificate AND a Transcript. If transcript missing -> FAIL.
*   ACAD-03 (Equivalency): Valid tracks: SSC + HSC OR SSC + Alim OR Dakhil + Alim OR SSC + Diploma. If valid combo -> PASS.
*   ACAD-04 (Name/DOB): Names must match StudentRef. SSC/Dakhil DOB must match Passport DOB. (Mismatch -> FLAG).

4.9 INCOME TAX (Optional)
*   TAX-01 (Presence): If no Income Tax pages are found -> PASS (Do not fail).
*   TAX-02 (Tax Limit): If Acknowledgment present, Total Tax Paid must be >= 10,000 BDT. If less -> FLAG.
*   TAX-03 (Wealth Limit): If Acknowledgment present, Total Income Shown must be >= 5,000,000 BDT. If less -> FLAG.
*   TAX-04 (Challan Verification): If Challan present, extract Challan No. Send a request to https://challanverification.finance.gov.bd/echalan/. Compare the Website Amount with the Printed Amount. If Match -> PASS. If Mismatch -> FAIL. If Internet fails -> FLAG. (Ignore all QR codes on Income Tax Certificate and Acknowledgment).

4.10 IELTS / TOPIK
*   LANG-01 (Expiry): Must be within 2 years. If expired -> FAIL.
*   LANG-02 (Name/DOB): Must match StudentRef. If mismatch -> FAIL (unless affidavit).

## SECTION 5: Global Cross-Checks

5.1 The Financial Chain (Strict Parent Match)
The engine extracts the names from the TIN Certificate and Trade License/Employment Certificate.
*   CHAIN-01: The TIN Taxpayer Name and Trade License Owner Name must be identical.
*   CHAIN-02: They must belong to the same parent. (If TIN=Father, Trade=Father -> PASS. If TIN=Father, Trade=Mother -> FAIL).
*   CHAIN-03: If either is in the StudentRef name -> FAIL. (Note: Bank is excluded from this chain).

5.2 Affidavit Coverage
*   If a name mismatch occurs (e.g., spelling difference), the engine checks the Affidavit.
*   If the Affidavit is notarized, explicitly states both spellings are the "same person," and matches the student/parent -> PASS.
*   If no Affidavit covers the mismatch -> FAIL.

## SECTION 6: Final Verdict Calculation
1. If any rule returns FAIL -> Overall Verdict = FAIL.
2. If no FAIL exists, but any rule returns FLAG -> Overall Verdict = FLAG (Needs Manual Review).
3. If only PASS -> Overall Verdict = PASS.
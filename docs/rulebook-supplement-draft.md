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

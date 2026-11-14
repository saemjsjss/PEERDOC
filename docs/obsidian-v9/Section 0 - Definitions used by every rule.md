# Section 0: Definitions used by every rule

Back to [[Home]]

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
    independent reading: the passport MRZ name ([[StudentRef]]), the passport date of birth
    ([[BIRTH-03]]), or another document's number of 8 or more digits, digit for digit ([[NID-03]],
    [[BANK-02]]).
  * Presence decides: only whether something is found matters (the notary text below,
    [[BANK-05]]; [[TRADE-03]], where no validity date is a FAIL).
  * Not checked when unsure: [[ACAD-06]] reports PASS with the reason "not checked".
  * Own threshold: [[STAMP-01]] uses 0.85.
* **Name match:** two names match when they are the same after cleanup, or the same words
  in another order. Cleanup ignores case, punctuation and spaces, drops a parentage suffix
  ("S/O ...", "D/O ...", "W/O ...", "C/O ..."), and treats the spellings of MD (MOHAMMAD,
  MOHAMMED, MUHAMMAD ...) and of MST (MOSAMMAT, MOSAMMET ...) as one title. A title is never
  dropped: "MST RAHIMA" and "RAHIMA" differ. Any other difference needs an affidavit (5.2).
* **Assigned by name:** a document's name is matched against the reference names of the
  people the rule allows ([[StudentRef]], [[FatherRef]], [[MotherRef]]; Section 2). A name matching
  exactly one allowed person -> PASS (assigned to them). Matching only a person who is
  not allowed (the student on a parent's document) -> FAIL. Matching nobody -> FAIL, but FLAG
  when an allowed person's reference name could not be read (the document may be theirs).
  Unreliable or not found, or matching two people -> FLAG ("could not be assigned with
  certainty"). An exact match wins over one bridged by an affidavit. Two NIDs, or two
  Death Certificates, assigned to the same person -> FLAG.
* **Translation:** a document "needs an English translation" FAILs only when it is in
  Bangla with no translation page. A bilingual (partly Bangla) document with no separate
  translation page is FLAG ([[BIRTH-01]] and [[NID-01]] name their exceptions). A translation page is known by
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

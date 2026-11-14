# Section 0: Conventions used by every rule

Back to [[Home]]

* Reliable: read with OCR confidence 0.90 or more. An unreliable or unreadable value gives
  FLAG, never a guess. Exceptions are named in their rule ([[BIRTH-03]], [[NID-03]], [[BANK-02]],
  [[BANK-05]], [[TRADE-03]], [[ACAD-06]], [[STAMP-01]], the notary text below, [[StudentRef]]).
* Check date: the case's evaluation date (default: the upload day). Every "within N months"
  counts back from the check date, on the same day of the month, and includes the end day.
* Missing documents: a missing document is reported only by its REQ rule (Section 3). The
  rules for that document type give no result.
* Name matching: names are compared after cleanup (case, punctuation and spacing ignored).
  The same words in another order are the same name. MD / MST match their common spellings
  (MOHAMMED, MUHAMMAD, MOSAMMET ...); other titles are kept. Any other spelling difference
  needs an affidavit (5.2).
* Missing reference name: when a parent's reference name could not be read at all, a
  document that might be that parent's is FLAG ("could not be assigned with certainty"),
  not FAIL. *(approved)*
* English translation ([[BIRTH-01]], [[TRADE-01]], [[EMP-01]], [[DEATH-02]]; [[NID-01]] is stricter): a document in Bangla
  without an English translation -> FAIL. A bilingual (partly Bangla) document without a
  separate translation page -> FLAG, except where its rule says otherwise ([[BIRTH-01]]). A
  translation page is recognised by its own wording ("translated", "translation", "true
  copy", "authorized to translate"); notary text alone does not make a notarised photocopy
  its own translation. When an agency stamp saying "Translation" is on every page, only the
  page carrying the translator's block ("TRUE COPY", "Translated by") is the translation.
  *(approved)*
* Notarised ([[NID-02]], [[BIRTH-02]], [[FRC-05]], [[TRADE-02]], [[EMP-02]], [[DEATH-03]], [[ACAD-05]]): the document has
  the "Notary Public" / "Advocate" text AND a notary stamp. Either one missing -> FAIL; a
  stamp that cannot be confirmed -> FLAG. The text only has to be found; a low OCR
  confidence on it does not make it doubtful. What counts as the stamp: *(approved)*
  * the notary's red foil seal (a large, solid red disc), whole or partly cut off at the
    page edge; a small round red logo, red text or an outline red rubber stamp does not;
  * a seal whose own ring text has a word starting with "NOTAR" or "ADVOCAT"; a seal whose
    text says something else (government emblem, Union Parishad, university, consular seal)
    does not;
  * a seal with no readable text, confirmed by "Notary Public" / "Advocate" printed next
    to it.

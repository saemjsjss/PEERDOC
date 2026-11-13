# Section 0: Conventions used by every rule

Back to [[Home]]

* Unreadable or low-confidence values (OCR confidence below 0.90) -> FLAG, never a guess.
  Exceptions are named in the rule ([[BIRTH-03]], [[NID-03]], [[BANK-02]], [[BANK-05]], [[TRADE-03]], [[ACAD-06]],
  [[STAMP-01]], the notary text in Section 0, [[StudentRef]]).
* Name matching is exact after cleanup. The same words in another order count as the same
  name. The MD / MST titles match their common spellings (MOHAMMED, MUHAMMAD, MOSAMMET ...).
  Other spelling differences need an affidavit (5.2).
* "If Bangla, must have English translation" ([[BIRTH-01]], [[TRADE-01]], [[EMP-01]], [[DEATH-02]]): FAIL
  only a document that is in Bangla without a translation; a bilingual (partly Bangla)
  document without a separate translation page is FLAG, except a bilingual birth
  certificate that gives every needed field in English ([[BIRTH-01]]). *(approved)*
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
  confirmed by "Notary Public" / "Advocate" printed next to it. *(approved)*
* "Must belong to the father or mother" rules: when a parent's reference name could not be
  read at all, a document that might be that parent's is FLAG ("could not be assigned with
  certainty"), not FAIL. *(approved)*

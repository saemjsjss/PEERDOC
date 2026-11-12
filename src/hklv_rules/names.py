"""Name normalisation.

Agreed policy: clean up case, punctuation, spacing, 'S/O ...'-style parentage
suffixes and the MD/MST abbreviations, then names must be identical. Anything
else (ASRAF vs ASHRAF, RAHIMA vs RAHIMA BEGUM, MST X vs X) is a mismatch that
only a notarised affidavit can bridge.
"""

from __future__ import annotations

import re
import unicodedata

# 'KAMAL UDDIN S/O: ABDUL KARIM & RAHIMA' -> 'KAMAL UDDIN'. Also D/O, W/O, C/O.
_PARENTAGE_SUFFIX = re.compile(r"\b[SDWC]\s*/\s*O\b.*$")

# The MD/MST titles and their common spellings all mean one title, so 'MD X' matches
# 'MOHAMMED X' as well as 'MOHAMMAD X'. Other spelling variants (ASRAF/ASHRAF) are NOT merged.
_ABBREVIATIONS = {
    **dict.fromkeys(("MD", "MOHD", "MOHAMMED", "MUHAMMAD", "MUHAMMED", "MOHAMMOD", "MOHAMAD"), "MOHAMMAD"),
    **dict.fromkeys(("MST", "MOST", "MOSAMMET", "MOSAMMOT", "MOSAMAT", "MUSAMMAT"), "MOSAMMAT"),
}


def normalize_name(raw: str) -> str:
    """Canonical comparison key. Spaces are dropped so 'ABU TAHER' == 'ABUTAHER'."""
    text = unicodedata.normalize("NFKC", raw).upper()
    text = _PARENTAGE_SUFFIX.sub("", text)
    tokens = re.findall(r"[A-Z]+", text)
    return "".join(_ABBREVIATIONS.get(t, t) for t in (_unglue(t) for t in tokens))


# OCR drops the space after the title: 'MSTRAHIMA' is 'MST RAHIMA'. No Bangladeshi name begins
# with the consonants MD or MST, so these prefixes are always the title (MOST- is left alone:
# MOSTAFA is a name).
_GLUED_TITLE = re.compile(r"^(MD|MST)(?=[A-Z]{3,})")


def _unglue(token: str) -> str:
    return _GLUED_TITLE.sub(lambda m: _ABBREVIATIONS[m.group(1)], token)


def names_equal(a: str, b: str) -> bool:
    key_a, key_b = normalize_name(a), normalize_name(b)
    return bool(key_a) and key_a == key_b


def _words(raw: str) -> list[str]:
    # MRZ fillers ('<') and punctuation separate words just like spaces.
    text = unicodedata.normalize("NFKC", raw).upper()
    return sorted(w for w in (normalize_name(t) for t in re.findall(r"[^\W\d_]+", text)) if w)


def same_name(a: str, b: str) -> bool:
    """names_equal, or the same words in another order (surname first on some documents)."""
    if names_equal(a, b):
        return True
    words_a = _words(a)
    return bool(words_a) and words_a == _words(b)


# Names hold no digits, so a digit in an MRZ name is an OCR slip ('AFR0Z' is 'AFROZ').
_DIGIT_TO_LETTER = str.maketrans({"0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B"})


def mrz_name_matches(mrz: str, printed: str) -> bool:
    """same_name, reading digits in the MRZ name as their look-alike letters."""
    return same_name(mrz.translate(_DIGIT_TO_LETTER), printed)

"""Name normalisation.

Agreed policy: clean up case, punctuation, spacing, 'S/O ...'-style parentage
suffixes and the MD/MST abbreviations, then names must be identical. Anything
else (ASRAF vs ASHRAF, HALIMA vs HALIMA BEGUM, MST X vs X) is a mismatch that
only a notarised affidavit can bridge.
"""

from __future__ import annotations

import re
import unicodedata

# 'ROHUL AMIN S/O: MANIK KHAN & HALIMA' -> 'ROHUL AMIN'. Also D/O, W/O, C/O.
_PARENTAGE_SUFFIX = re.compile(r"\b[SDWC]\s*/\s*O\b.*$")

# Abbreviations only; spelling variants (MOHAMMED, MUHAMMAD) are NOT merged.
_ABBREVIATIONS = {
    "MD": "MOHAMMAD",
    "MOHD": "MOHAMMAD",
    "MST": "MOSAMMAT",
    "MOST": "MOSAMMAT",
}


def normalize_name(raw: str) -> str:
    """Canonical comparison key. Spaces are dropped so 'ABU TAHER' == 'ABUTAHER'."""
    text = unicodedata.normalize("NFKC", raw).upper()
    text = _PARENTAGE_SUFFIX.sub("", text)
    tokens = re.findall(r"[A-Z]+", text)
    return "".join(_ABBREVIATIONS.get(t, t) for t in tokens)


def names_equal(a: str, b: str) -> bool:
    key_a, key_b = normalize_name(a), normalize_name(b)
    return bool(key_a) and key_a == key_b

"""Date parsing for Bangladeshi documents: always day-first, never guessed."""

from __future__ import annotations

import re
from datetime import date

_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("JAN", "JANUARY"), ("FEB", "FEBRUARY"), ("MAR", "MARCH"), ("APR", "APRIL"), ("MAY",),
            ("JUN", "JUNE"), ("JUL", "JULY"), ("AUG", "AUGUST"), ("SEP", "SEPT", "SEPTEMBER"),
            ("OCT", "OCTOBER"), ("NOV", "NOVEMBER"), ("DEC", "DECEMBER"),
        ],
        start=1,
    )
    for m in names
}
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))

_NUMERIC = re.compile(r"\b(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{4})\b")
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DAY_MONTH = re.compile(r"\b(\d{1,2})(?:ST|ND|RD|TH)?[\s\-.,/]*(" + _MONTH_RE + r")[A-Z]*[\s\-.,/']*(\d{4})\b", re.IGNORECASE)
_MONTH_DAY = re.compile(r"\b(" + _MONTH_RE + r")[A-Z]*[\s\-.]*(\d{1,2})(?:ST|ND|RD|TH)?,?\s*(\d{4})\b", re.IGNORECASE)


def _make(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def find_dates(text: str) -> list[date]:
    """Every unambiguous calendar date in `text`, in order of appearance."""
    hits: list[tuple[int, date]] = []
    for m in _ISO.finditer(text):
        if (d := _make(int(m[1]), int(m[2]), int(m[3]))) is not None:
            hits.append((m.start(), d))
    for m in _NUMERIC.finditer(text):
        if (d := _make(int(m[3]), int(m[2]), int(m[1]))) is not None:
            hits.append((m.start(), d))
    for m in _DAY_MONTH.finditer(text):
        if (d := _make(int(m[3]), _MONTHS[m[2].upper()], int(m[1]))) is not None:
            hits.append((m.start(), d))
    for m in _MONTH_DAY.finditer(text):
        if (d := _make(int(m[3]), _MONTHS[m[1].upper()], int(m[2]))) is not None:
            hits.append((m.start(), d))
    return [d for _, d in sorted(hits, key=lambda h: h[0])]


def parse_date(text: str) -> date | None:
    """The single date in `text`; None if there is none or several different ones."""
    found = set(find_dates(text))
    return found.pop() if len(found) == 1 else None


# --- dates written in words: "Fifth August Two Thousand" (SSC/HSC certificates) ---------

_ORDINALS = {
    w: i
    for i, w in enumerate(
        "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth "
        "fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth".split(),
        start=1,
    )
}
_ORDINALS.update({f"twenty {w}": 20 + i for w, i in list(_ORDINALS.items()) if i <= 9})
_ORDINALS.update({"thirtieth": 30, "thirty first": 31})
_UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}


def _small_number(words: list[str]) -> int | None:
    """'ninety eight' -> 98, 'five' -> 5 (0-99)."""
    if not words:
        return 0
    if len(words) == 1:
        return _UNITS.get(words[0], _TENS.get(words[0]))
    if len(words) == 2 and words[0] in _TENS and words[1] in _UNITS and 0 < _UNITS[words[1]] < 10:
        return _TENS[words[0]] + _UNITS[words[1]]
    return None


def _year_words(words: list[str]) -> int | None:
    """'two thousand', 'two thousand one', 'nineteen ninety eight',
    'one thousand nine hundred ninety eight'."""
    if words[:2] == ["two", "thousand"]:
        rest = _small_number([w for w in words[2:] if w != "and"])
        return None if rest is None else 2000 + rest
    if words[:4] == ["one", "thousand", "nine", "hundred"]:
        rest = _small_number([w for w in words[4:] if w != "and"])
        return None if rest is None else 1900 + rest
    if words and words[0] == "nineteen":
        rest = _small_number(words[1:])
        return None if rest is None or rest == 0 else 1900 + rest
    return None


_WORDS_DATE = re.compile(
    r"\b((?:twenty|thirty)?\s*[a-z]+?(?:st|nd|rd|th))\s+(" + "|".join(n.lower() for n in sorted(_MONTHS, key=len, reverse=True) if len(n) > 3 or n == "MAY") + r")\s+((?:[a-z]+\s*){1,7})",
    re.IGNORECASE,
)


def parse_words_date(text: str) -> date | None:
    """A date written out in words; None unless it parses completely."""
    m = _WORDS_DATE.search(re.sub(r"\s+", " ", text))
    if not m:
        return None
    day = _ORDINALS.get(re.sub(r"\s+", " ", m.group(1).strip().lower()))
    month = _MONTHS[m.group(2).upper()]
    words = re.findall(r"[a-z]+", m.group(3).lower())
    # Try the longest run of year words first ("two thousand one" before "two thousand").
    for n in range(len(words), 1, -1):
        year = _year_words(words[:n])
        if year is not None and day is not None:
            return _make(year, month, day)
    return None

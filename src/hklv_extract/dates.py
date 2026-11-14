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

_NUMERIC = re.compile(r"\b(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{4})\b|\b(\d{1,2})\.(\d{1,2}),(\d{4})\b")
# second form: a dot read as a comma ('25.10,2026'); only tight to the digits, never '8, 2, 1902'
# Year first is unambiguous with any separator: '2003-04-05', '2003/04/05' (TOPIK), '2003.04.05'.
_ISO = re.compile(r"(?<!\d)(\d{4})([-/.])(\d{2})\2(\d{2})(?!\d)")
_DAY_MONTH = re.compile(r"\b(\d{1,2})(?:ST|ND|RD|TH)?[\s\-.,/]*(" + _MONTH_RE + r")(?![A-Z])[\s\-.,/']*(\d{4})\b", re.IGNORECASE)
_MONTH_DAY = re.compile(r"\b(" + _MONTH_RE + r")(?![A-Z])[\s\-.]*(\d{1,2})(?:ST|ND|RD|TH)?,?\s*(\d{4})\b", re.IGNORECASE)


def _make(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def find_dates(text: str) -> list[date]:
    """Every unambiguous calendar date in `text`, in order of appearance."""
    hits: list[tuple[int, date]] = []
    for m in _ISO.finditer(text):
        if (d := _make(int(m[1]), int(m[3]), int(m[4]))) is not None:
            hits.append((m.start(), d))
    for m in _NUMERIC.finditer(text):
        day, month, year = m.groups()[:3] if m[1] else m.groups()[3:]
        if (d := _make(int(year), int(month), int(day))) is not None:
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


_MONTH_WORD = re.compile(r"\b(?:" + _MONTH_RE + r")[A-Z]*\b", re.IGNORECASE)


def has_month_name(text: str) -> bool:
    """'8th May, 2006', 'Fifth August Two Thousand One': the month is written as a word."""
    return bool(_MONTH_WORD.search(text))


def parse_boxed_date(text: str) -> date | None:
    """A date written one or two digits per box: '08 05 2006', '0 8 0 5 2 0 0 6', '08052006'.

    Only for a value already found after a date label, and only if it is exactly eight
    digits. Day-first (DDMMYYYY) as every Bangladeshi form; YYYYMMDD only when that is the
    sole valid reading. If both read as different valid dates, nothing is returned.
    """
    # Box borders and the filled square some forms print between month and year
    # ('25 | 02 | ■ | 2002') read as | [ ] I l or a block character: not digits.
    text = re.sub(r"[|\[\]Il■-▫█]", " ", text or "")
    if not re.fullmatch(r"[\d\s]+", text):
        return None
    d = re.sub(r"\s", "", text)
    if len(d) == 9 and re.fullmatch(r"\d{2}\s+\d{2}\s+\d\s+\d{4}", text.strip()):
        d = d[:4] + d[5:]  # the filled square read as one digit of its own
    if len(d) != 8:
        return None
    day_first = _make(int(d[4:]), int(d[2:4]), int(d[:2])) if 1900 <= int(d[4:]) <= 2100 else None
    year_first = _make(int(d[:4]), int(d[4:6]), int(d[6:])) if 1900 <= int(d[:4]) <= 2100 else None
    if day_first and year_first and day_first != year_first:
        return None
    return day_first or year_first


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


_SCALES = {"hundred": 100, "thousand": 1000, "lakh": 100_000, "lac": 100_000, "crore": 10_000_000}


def parse_amount_words(text: str) -> int | None:
    """'Three Thousand Taka Only' -> 3000, 'One Lakh Twenty Five Thousand' -> 125000.
    None unless every word is understood."""
    words = [w for w in re.findall(r"[a-z]+", text.lower()) if w not in ("and", "taka", "tk", "only")]
    total = current = 0
    run: list[str] = []
    for w in words:
        if w in _SCALES:
            n = _small_number(run)
            if not n:
                return None
            run = []
            if w == "hundred":
                current += n * 100
            else:
                total += (current + n) * _SCALES[w]
                current = 0
        elif w in _UNITS or w in _TENS:
            run.append(w)
        else:
            return None
    n = _small_number(run)
    return None if n is None or not words else total + current + n


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
    # "Twenty-Fifth", "Thirty - First": without this the match starts at "Fifth" / "First".
    m = _WORDS_DATE.search(re.sub(r"\s+", " ", re.sub(r"\s*-\s*", " ", text)))
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

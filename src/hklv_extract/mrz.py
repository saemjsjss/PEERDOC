"""Machine-readable zone (MRZ) parsing with ICAO 9303 check digits.

Supports TD3 (passport: 2 lines x 44) and TD1 (ID card, e.g. Bangladesh smart NID:
3 lines x 30). OCR text is repaired only where the repair is guarded by a check digit:
characters in numeric fields are mapped to look-alike digits (O->0, I->1, ...), and the
result is accepted only if the check digits then validate. Names have no check digit, so
they are never "corrected"; they are confirmed by agreement with the printed name instead.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

TD1_LEN, TD3_LEN = 30, 44
_WEIGHTS = (7, 3, 1)
_TO_DIGIT = str.maketrans({"O": "0", "Q": "0", "D": "0", "U": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "G": "6", "B": "8", "T": "7"})
_TO_ALPHA = str.maketrans({"0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B"})
# Characters OCR produces for MRZ glyphs that are not in the MRZ alphabet.
_OCR_FIXES = str.maketrans({"|": "I", "∪": "U", "«": "<", "‹": "<", "(": "<", "{": "<", "[": "<", "К": "K", "С": "C", "О": "O", "Р": "P", "Н": "H", "М": "M", "А": "A", "В": "B", "Е": "E", "Т": "T", "Х": "X"})


class MrzResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    format: Literal["TD1", "TD3"]
    document_code: str
    issuing_state: str
    document_number: str
    nationality: str
    birth_date: date | None
    sex: str
    expiry_date: date | None
    surname: str
    given_names: str
    personal_number: str = ""
    checks: dict[str, bool]
    lines: tuple[str, ...]

    @property
    def valid(self) -> bool:
        """Every check digit validates and both dates are real calendar dates."""
        return all(self.checks.values()) and self.birth_date is not None and self.expiry_date is not None

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.given_names, self.surname) if p)


def check_digit(field: str) -> int:
    total = 0
    for i, ch in enumerate(field):
        if ch.isdigit():
            v = int(ch)
        elif "A" <= ch <= "Z":
            v = ord(ch) - 55
        else:  # '<' and anything unexpected
            v = 0
        total += v * _WEIGHTS[i % 3]
    return total % 10


def _check_ok(field: str, digit: str) -> bool:
    # A field that is entirely filler may carry '<' as its check digit.
    if digit == "<":
        return set(field) <= {"<"}
    return digit.isdigit() and int(digit) == check_digit(field)


def clean_line(text: str) -> str:
    """Uppercase, map OCR look-alikes, drop spaces and anything outside [A-Z0-9<]."""
    t = text.upper().translate(_OCR_FIXES)
    return re.sub(r"[^A-Z0-9<]", "", t)


def _fit(line: str, length: int) -> str | None:
    """Make a line exactly `length` long by adjusting only its trailing filler."""
    if len(line) == length:
        return line
    body = line.rstrip("<")
    if len(body) > length:
        return None
    if len(line) > length or line.endswith("<"):
        return body.ljust(length, "<")
    return None  # too short and doesn't end in filler: something real is missing


def _digits(s: str) -> str:
    return s.translate(_TO_DIGIT)


def _alpha(s: str) -> str:
    return s.translate(_TO_ALPHA)


def _date(yymmdd: str, *, birth: bool, today: date) -> date | None:
    if not yymmdd.isdigit():
        return None
    yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
    year = 2000 + yy
    if birth and year > today.year:
        year -= 100
    try:
        return date(year, mm, dd)
    except ValueError:
        return None


def _name(field: str) -> tuple[str, str]:
    field = field.rstrip("<")
    surname, _, given = field.partition("<<")
    return surname.replace("<", " ").strip(), given.replace("<", " ").strip()


def parse_td3(lines: Sequence[str], today: date) -> MrzResult | None:
    if len(lines) != 2:
        return None
    l1, l2 = (_fit(clean_line(x), TD3_LEN) for x in lines)
    if l1 is None or l2 is None or not l1.startswith(("P", "1")):
        return None
    l1 = "P" + l1[1:]
    number, number_cd = l2[0:9], _digits(l2[9])
    birth, birth_cd = _digits(l2[13:19]), _digits(l2[19])
    expiry, expiry_cd = _digits(l2[21:27]), _digits(l2[27])
    personal, personal_cd = l2[28:42], l2[42] if l2[42] == "<" else _digits(l2[42])
    composite_cd = _digits(l2[43])
    fixed = number + number_cd + _alpha(l2[10:13]) + birth + birth_cd + l2[20] + expiry + expiry_cd + personal + personal_cd
    surname, given = _name(l1[5:])
    return MrzResult(
        format="TD3",
        document_code=l1[0:2].rstrip("<"),
        issuing_state=_alpha(l1[2:5]),
        document_number=number.rstrip("<"),
        nationality=_alpha(l2[10:13]),
        birth_date=_date(birth, birth=True, today=today),
        sex=l2[20],
        expiry_date=_date(expiry, birth=False, today=today),
        surname=surname,
        given_names=given,
        personal_number=personal.rstrip("<"),
        checks={
            "document_number": _check_ok(number, number_cd),
            "birth_date": _check_ok(birth, birth_cd),
            "expiry_date": _check_ok(expiry, expiry_cd),
            "personal_number": _check_ok(personal, personal_cd),
            "composite": _check_ok(fixed[0:10] + fixed[13:20] + fixed[21:43], composite_cd),
        },
        lines=(l1, l2),
    )


def parse_td1(lines: Sequence[str], today: date) -> MrzResult | None:
    if len(lines) != 3:
        return None
    l1, l2, l3 = (_fit(clean_line(x), TD1_LEN) for x in lines)
    if l1 is None or l2 is None or l3 is None or not l1.startswith(("I", "1", "A", "C")):
        return None
    if l1[0] == "1":
        l1 = "I" + l1[1:]
    number, number_cd = l1[5:14], l1[14]
    if number_cd == "<" and l1[15:30].strip("<"):
        # Long document number (e.g. 10-digit NID): it continues in the optional data,
        # followed by its check digit and a filler.
        rest = l1[15:30].split("<", 1)[0]
        number, number_cd = number + rest[:-1], rest[-1:]
    number_ok = False
    for candidate, cd in ((number, number_cd), (_digits(number), _digits(number_cd))):
        if _check_ok(candidate, cd):
            number, number_ok = candidate, True
            break
    birth, birth_cd = _digits(l2[0:6]), _digits(l2[6])
    expiry, expiry_cd = _digits(l2[8:14]), _digits(l2[14])
    composite_cd = _digits(l2[29])
    composite_field = l1[5:30] + birth + birth_cd + expiry + expiry_cd + l2[18:29]
    surname, given = _name(l3)
    return MrzResult(
        format="TD1",
        document_code=l1[0:2].rstrip("<"),
        issuing_state=_alpha(l1[2:5]),
        document_number=number.rstrip("<"),
        nationality=_alpha(l2[15:18]),
        birth_date=_date(birth, birth=True, today=today),
        sex=l2[7],
        expiry_date=_date(expiry, birth=False, today=today),
        surname=surname,
        given_names=given,
        checks={
            "document_number": number_ok,
            "birth_date": _check_ok(birth, birth_cd),
            "expiry_date": _check_ok(expiry, expiry_cd),
            "composite": _check_ok(composite_field, composite_cd),
        },
        lines=(l1, l2, l3),
    )


def _looks_like_mrz(text: str) -> bool:
    t = clean_line(text)
    return len(t) >= 20 and (t.count("<") >= 3 or re.fullmatch(r"[A-Z0-9<]{28,46}", t) is not None and t.count("<") >= 1)


def find_mrz(texts: Sequence[str], today: date) -> list[MrzResult]:
    """Every TD3/TD1 zone that parses from consecutive OCR lines, best (most checks valid) first."""
    found: list[MrzResult] = []
    for i in range(len(texts)):
        if not _looks_like_mrz(texts[i]):
            continue
        if i + 1 < len(texts):
            r = parse_td3(texts[i : i + 2], today)
            if r is not None:
                found.append(r)
        if i + 2 < len(texts) and _looks_like_mrz(texts[i + 1]):
            r = parse_td1(texts[i : i + 3], today)
            if r is not None:
                found.append(r)
    found.sort(key=lambda r: (r.valid, sum(r.checks.values())), reverse=True)
    return found

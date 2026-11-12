"""Field extractors: one page group in, one typed rules-engine document out.

Every value carries a confidence from `confidence.py`. Nothing is filled in by guesswork:
a field that can't be found stays empty, which the rules engine treats as FLAG.
"""

from __future__ import annotations

import html
import re
from itertools import permutations
from collections.abc import Callable, Sequence
from datetime import date
from decimal import Decimal, InvalidOperation

from hklv_ocr.reading import PageReading, TextLine
from hklv_rules.models import documents as m
from hklv_rules.models.common import Extracted, NotaryInfo, Person

from .classify import PageKind
from .common_fields import document_language, has_translation, notary_info, page_language
from .confidence import AGREE_CAP, DISAGREE, MRZ_INVALID, MRZ_VALID, SINGLE_READER_FACTOR, VL_ONLY, date_field, derived, score_text, text_field
from .dates import find_dates, has_month_name, parse_amount_words, parse_boxed_date, parse_date, parse_words_date
from .group import PageGroup
from .mrz import MrzResult
from .text import ROW_FIRST_GAP_PX, Found, as_lines_page, clean_value, find_labeled, levenshtein, line_under, reading_order, same_row, squash

NAME = r"[A-Za-z][A-Za-z .\-']{1,60}"
# Labels that often follow a name on the same printed line.
NAME_STOPS = (
    r"Father", r"Mother", r"Husband", r"Spouse", r"Date", r"Sex", r"Gender", r"Nationality", r"Country", r"Place",
    r"Address", r"NID", r"ID\s*No", r"A/C", r"Birth", r"Blood", r"Relation", r"S/O", r"D/O", r"W/O", r"Son\s+of",
)


# --- helpers ---------------------------------------------------------------------------


def _first(group: PageGroup, finder: Callable[[PageReading], Found | None], pages: Sequence[PageReading] | None = None):
    """First page where PP-OCRv6's lines give the value; else PaddleOCR-VL's text alone.

    A value only the second reader saw scores VL_ONLY (below threshold: FLAG). It is
    still better evidence than nothing, e.g. for one-digit-per-box numbers that PP-OCRv6
    partly misses.
    """
    pages = list(pages if pages is not None else group.pages)
    for page in pages:
        found = finder(page)
        if found is not None:
            return found, page
    for page in pages:
        found = finder(as_lines_page(page, VL_ONLY))
        if found is not None:
            return found, page
    return None, None


def _name(group: PageGroup, labels: Sequence[str], pages: Sequence[PageReading] | None = None) -> Extracted[str]:
    found, page = _first(
        group, lambda p: find_labeled(p, labels, value_pattern=NAME, stop_words=NAME_STOPS), pages
    )
    return text_field(found, page)


def _text(group: PageGroup, labels: Sequence[str], pattern: str, pages: Sequence[PageReading] | None = None) -> Extracted[str]:
    found, page = _first(group, lambda p: find_labeled(p, labels, value_pattern=pattern), pages)
    if found is not None:
        found = Found(re.sub(r"\s+", "", found.value) if re.fullmatch(r"[\d\s\-/]+", found.value) else found.value, found.score, found.page_no)
    return text_field(found, page)


# A date value must contain a 4-digit year. Lines without one (another label such as
# "Holder's Signature" between "Date of Expiry" and "03JUN2033") are skipped.
DATE_VALUE = r".{0,30}\d{4}.{0,15}"

# A person's own 'Name' label, never a relative's: OCR often drops the apostrophe
# ('Fathers Name', 'Father s Name'), so every spelling is excluded.
_RELATIVES = ("Father", "Mother", "Husband", "Spouse", "Guardian")
OWN_NAME = "".join(
    f"(?<!{who}{tail} )" for who in _RELATIVES for tail in ("'s", "’s", "s", " s", "")
) + r"\bName\b(?!\s*of)"
# A letter's own date ('Date: 10/11/2026', 'Dated ...'), not 'Account Opening Date' or 'Date of ...'.
# 'Print Date' counts: bank letters printed from the core system carry only that.
LETTER_DATE = [
    "".join(f"(?<!{w} )" for w in ("Opening", "Open", "Value", "Maturity", "Starting", "Expiry", "Birth", "Transaction"))
    + r"\bDate(?![A-Za-z])(?!\s*of)",  # 'Print Date15-Jun-2025': OCR lost the space
    r"\bDated\b",
]


def _date(
    group: PageGroup, labels: Sequence[str], pages: Sequence[PageReading] | None = None, *, boxed: bool = False
) -> Extracted[date]:
    """`boxed`: also read eight digits written one or two per box ('08 05 2006'). Only for
    fields printed that way (a birth certificate's date of birth): elsewhere an 8-digit ID
    on the line after a date label could form a valid date."""
    found, page = _first(group, lambda p: find_labeled(p, labels, value_pattern=DATE_VALUE), pages)
    if found is None:
        return Extracted[date]()
    d = parse_date(found.value) or (parse_boxed_date(found.value) if boxed else None)
    if d is None:
        return Extracted[date]()
    return date_field(d, score_text(found, page), found.page_no)


def _mrz(group: PageGroup) -> MrzResult | None:
    zones = [c.mrz for c in group.classes if c.mrz is not None]
    zones.sort(key=lambda z: (z.valid, sum(z.checks.values())), reverse=True)
    return zones[0] if zones else None


def _mrz_conf(mrz: MrzResult, check: str) -> float:
    return MRZ_VALID if mrz.checks.get(check) and mrz.checks.get("composite", True) else MRZ_INVALID


def _mrz_page(group: PageGroup, mrz: MrzResult) -> int:
    for c in group.classes:
        if c.mrz is mrz:
            return c.page_no
    return group.pages[0].page_no


def _agree_with_mrz(printed: Extracted[str], mrz_name: str) -> Extracted[str]:
    """Printed name confirmed by the MRZ (word order ignored) is as good as two readers."""
    if printed.value is None or not mrz_name:
        return printed
    words = [w for w in mrz_name.split() if w]
    if sorted(squash(w) for w in printed.value.split()) == sorted(squash(w) for w in words):
        return Extracted[str](value=printed.value, confidence=max(printed.confidence, AGREE_CAP), source_page=printed.source_page)
    # Same letters, spacing lost on the card ("KARIMUDDIN"): take the MRZ's word breaks, in
    # the printed order. No letter is changed.
    for order in permutations(words):
        if squash("".join(order)) == squash(printed.value):
            return Extracted[str](value=" ".join(order), confidence=max(printed.confidence, AGREE_CAP), source_page=printed.source_page)
    return printed


# What makes an NID page a translation. Notary text alone does not: a notarised photocopy
# of the card carries "Notary Public" / "Advocate" too, and must not count as its own
# translation (NID-01/NID-03 would then pass with no translation page).
NID_TRANSLATION_RE = re.compile(
    r"\btranslat(?:ed|ion)\b"
    r"|\btrue\s*copy\b"
    r"|\bauthori[sz]ed\s+to\s+translate\b"
    r"|\benglish\s+version\b",
    re.IGNORECASE,
)
# A single page cannot reliably be both the card and its separate translation.
SINGLE_PAGE_NO_TRANSLATION = 0.6


_TRANSLATOR_BLOCK = re.compile(r"\btrue\s*copy\b|\btranslated\s*by\b", re.IGNORECASE)


def _translation_pages(group: PageGroup) -> list[PageReading]:
    """Pages that are the separate translation of the card: they carry a translation marker.

    If no page or every page is marked, the group has no separate translation page and the
    result is empty (the card page is never also read as the translation).
    """
    marked = [p for p in group.pages if NID_TRANSLATION_RE.search(p.line_text) or NID_TRANSLATION_RE.search(p.block_text)]
    if len(marked) == len(group.pages):
        # The agency's round stamp says 'Translation' on the card copy too; only the
        # translation itself carries the translator's block.
        marked = [p for p in marked if _TRANSLATOR_BLOCK.search(p.line_text) or _TRANSLATOR_BLOCK.search(p.block_text)]
    if not marked or len(marked) == len(group.pages):
        return []
    return marked


def _nid_has_translation(group: PageGroup, translation: Sequence[PageReading]) -> Extracted[bool]:
    if translation:
        return Extracted[bool](value=True, confidence=0.95, source_page=translation[0].page_no)
    found = has_translation(group.pages)
    if len(group.pages) == 1 and found.value:
        # The only page is the card: not a confirmed translation, not a confirmed absence.
        return Extracted[bool](value=False, confidence=SINGLE_PAGE_NO_TRANSLATION, source_page=group.pages[0].page_no)
    return found


def _notary(group: PageGroup) -> NotaryInfo:
    return notary_info(group.pages)


def _tables(page: PageReading) -> list[list[list[str]]]:
    """PaddleOCR-VL table blocks as rows of cell texts."""
    out = []
    for b in page.blocks:
        if b.label != "table" or "<tr" not in b.text.lower():
            continue
        rows = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", b.text, re.IGNORECASE | re.DOTALL):
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.IGNORECASE | re.DOTALL)
            rows.append([clean_value(html.unescape(re.sub(r"<[^>]+>", " ", c))) for c in cells])
        out.append(rows)
    return out


MAX_SPAN = 50  # a rowspan/colspan larger than this is an OCR artefact, not a real table


def _span(attrs: str, name: str) -> int:
    mt = re.search(name + r"""\s*=\s*["']?(\d{1,6})""", attrs, re.IGNORECASE)
    return max(1, min(int(mt.group(1)), MAX_SPAN)) if mt else 1


def _table_grid(table_html: str) -> list[list[str | None]]:
    """One VL table as a full grid of cell texts.

    A merged cell (rowspan/colspan) fills every slot it covers, so index j is the same
    column in every row. Without this, a header cell spanning two rows ("Sl. No.") shifts
    the next header row one place left of the data rows beneath it. A slot no cell covers
    is None: a row with a missing cell is then shorter than its header row.
    """
    grid: dict[tuple[int, int], str] = {}
    for r, tr in enumerate(re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.IGNORECASE | re.DOTALL)):
        c = 0
        for attrs, raw in re.findall(r"<t[dh]([^>]*)>(.*?)</t[dh]>", tr, re.IGNORECASE | re.DOTALL):
            while (r, c) in grid:
                c += 1
            text = clean_value(html.unescape(re.sub(r"<[^>]+>", " ", raw)))
            rows, cols = _span(attrs, "rowspan"), _span(attrs, "colspan")
            for dr in range(rows):
                for dc in range(cols):
                    grid.setdefault((r + dr, c + dc), text)
            c += cols
    if not grid:
        return []
    n_rows, n_cols = max(r for r, _ in grid) + 1, max(c for _, c in grid) + 1
    return [[grid.get((r, c)) for c in range(n_cols)] for r in range(n_rows)]


def _header_re(labels: Sequence[str]) -> re.Pattern[str]:
    """The whole cell or line is the label (a column header), not 'Label: value'."""
    return re.compile(r"(?:" + "|".join(labels) + r")\s*[:：]?", re.IGNORECASE)


def _compact(value: str) -> str:
    """'0123 4567 890' -> '01234567890': a numeric value without spaces, as _text gives it."""
    return re.sub(r"\s+", "", value) if re.fullmatch(r"[\d\s\-/]+", value) else value


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _digit_runs(text: str) -> set[str]:
    """Every whole number written in `text`, as digits only: runs joined by dashes, and runs
    joined by dashes or spaces. A number is never matched inside a longer one, so
    '123456789012' is not in '0123456789012'."""
    runs = re.findall(r"\d[\d\-]*\d|\d", text) + re.findall(r"\d[\d \-]*\d", text)
    return {_digits(r) for r in runs}


def _near_number(target: str, text: str) -> bool:
    """Another reader wrote a number one or two digits away from `target` (a misread)."""
    return any(
        abs(len(run) - len(target)) <= 2 and levenshtein(run, target, limit=2) <= 2
        for run in _digit_runs(text)
        if run != target and len(run) >= 4
    )


COLUMN_MAX_DROP_PX = 600  # header -> its value further down the same column (300 dpi)
COLUMN_ONE_READER = VL_ONLY  # a column value only one reader's structure gives: FLAG
# A value only the fallback lookups added for layouts the label lookups can't read (a
# details-table column, a "BR Number" row, a boxed or in-words date of birth) is evidence
# for the reviewer, never confident on its own: each has layouts where it reads another
# field confidently (a second account, a parent's number, a registration date), and a
# confident wrong value FAILs a correct case where a missing one only FLAGs.
FALLBACK_MAX = VL_ONLY

# A header row with any of these is a transaction / transfer table: its "Account Number"
# column holds the other party's account, never the holder's.
_TX_WORDS = re.compile(
    r"DEBIT|CREDIT|WITHDRAW|DEPOSIT|PARTICULARS|NARRATION|DESCRIPTION|CHEQUE|\bCHQ\b"
    r"|TRANSACTION|\bTXN\b|VALUE\s*DATE|REMARKS|BENEFICIARY|COUNTERPARTY|\bDR\b|\bCR\b",
    re.IGNORECASE,
)


# Six or more digits, possibly grouped by single spaces or dashes: account-sized.
_LONG_RUN = re.compile(r"\d(?:[\s\-]?\d){5,}")
# "1 0123456789012": a row's serial number read together with the account number, by one
# reader or by both alike (a narrow Sl. No. column). Never taken as an account number.
_JOINED_SERIAL = re.compile(r"\d{1,2}\s+\d(?:[\s\-]?\d){5,}")


def _in_tx_header_row(h: TextLine, lines: Sequence[TextLine]) -> bool:
    """A transaction word on any line overlapping the header's height. Not same_row: wrapped
    headers ('Particulars of / Transaction') sit half a line above and below it."""
    return any(
        ln is not h and ln.box[1] < h.box[3] and ln.box[3] > h.box[1] and _TX_WORDS.search(ln.text) for ln in lines
    )


def _column_line(page: PageReading, labels: Sequence[str], pattern: str) -> TextLine | None:
    """PP-OCRv6: the line right under a header line that is exactly the label.

    Strict, because a wrong number read confidently FAILs a correct case while a missing
    one only FLAGs. None when the line under the header is not wholly a number, reaches
    outside the header's column (it was joined with a neighbouring cell), is followed
    closely by more digits (the number wrapped onto a second line), or when the column
    holds another, different number further down (a second account, or another field).
    """
    header_re, value_re = _header_re(labels), re.compile(pattern)
    picked: list[TextLine] = []
    for h in page.lines:
        if not header_re.fullmatch(clean_value(h.text)):
            continue
        if _in_tx_header_row(h, page.lines):
            continue  # a transaction table's header row
        half = (h.box[2] - h.box[0]) / 2
        lo, hi = h.box[0] - half, h.box[2] + half
        below = sorted(
            (
                ln
                for ln in page.lines
                if ln is not h
                and h.box[3] - 5 <= ln.box[1] <= h.box[3] + COLUMN_MAX_DROP_PX
                and lo <= (ln.box[0] + ln.box[2]) / 2 <= hi
            ),
            key=lambda ln: ln.box[1],
        )
        # The cell right under the header: the first line overlapping the header's own width.
        # A narrow neighbouring column's cell (the serial "1") can sit inside the band.
        first = next((ln for ln in below if ln.box[0] < h.box[2] and ln.box[2] > h.box[0]), None)
        if first is None:
            continue
        rest = [ln for ln in below if ln is not first]
        if not value_re.fullmatch(clean_value(first.text)) or first.box[0] < lo or first.box[2] > hi:
            return None
        if _JOINED_SERIAL.fullmatch(clean_value(first.text)):
            return None
        height = max(1, first.box[3] - first.box[1])
        x0, x1 = first.box[0], first.box[2]
        # Digits starting within a line height under it, overlapping it: a wrapped number.
        if any(re.search(r"\d", ln.text) and ln.box[1] - first.box[3] <= height and ln.box[0] < x1 and ln.box[2] > x0 for ln in rest):
            return None
        # Any other account-sized number in the column, even inside a line OCR joined with a
        # neighbouring cell ("2 0987654321098"): a second account, or another field. The
        # letter's own text below ("Exchange Rate: 124.25 ...", "Date: 29.10.2026") has none.
        mine = _digits(first.text)
        if any(_digits(run) != mine for ln in rest for run in _LONG_RUN.findall(ln.text)):
            return None
        picked.append(first)
    return picked[0] if picked and len({_digits(ln.text) for ln in picked}) == 1 else None


def _column_cell(page: PageReading, labels: Sequence[str], pattern: str) -> tuple[str, str | None]:
    """PaddleOCR-VL: the number in the table column under a header cell that is exactly the
    label.

    ('none', None): no VL table has that header. ('tx', None): it is only in a transaction
    table's header row (the other party's account). ('value', v): every digit-bearing cell in
    the column is that same number. ('unclear', None): the header is there but the column
    decides nothing: several different numbers, a masked or partial one, no number, or a
    row that does not line up with the header row (a missing, extra or unclosed cell, a
    nested table), where a neighbouring column's value may sit under the header.
    """
    header_re, value_re = _header_re(labels), re.compile(pattern)
    found_header = in_tx = False
    values: list[str] = []
    for b in page.blocks:
        if b.label != "table" or "<tr" not in b.text.lower():
            continue
        nested = b.text.lower().count("<table") > 1
        grid = _table_grid(b.text)
        for i, row in enumerate(grid):
            for j, cell in enumerate(row):
                if cell is None or not header_re.fullmatch(cell):
                    continue
                if any(c and _TX_WORDS.search(c) for c in row):
                    in_tx = True
                    continue  # a transaction table's header row
                found_header = True
                width = sum(c is not None for c in row)
                for r in grid[i + 1 :]:
                    if nested or sum(c is not None for c in r) != width:
                        return ("unclear", None)
                    below = r[j]
                    if below is None or below == cell or not re.search(r"\d", below):
                        continue  # the header repeated by a rowspan, an empty or text cell
                    if not value_re.fullmatch(below) or _JOINED_SERIAL.fullmatch(below):
                        return ("unclear", None)
                    values.append(_compact(below))
    if not found_header:
        return ("tx", None) if in_tx else ("none", None)
    if values and len({_digits(v) for v in values}) == 1:
        return ("value", values[0])
    return ("unclear", None)


# Wholly a numeric date ("05-10-2026", "2026-10-05"): an Open Date cell, not an account.
_WHOLE_DATE = re.compile(r"\d{1,2}\s*[/\-.]\s*\d{1,2}\s*[/\-.]\s*(?:19|20)\d{2}|(?:19|20)\d{2}-\d{2}-\d{2}")
_ACCOUNT_WORD = re.compile(r"\bA\s*/?\s*C\b|ACCOUNT", re.IGNORECASE)


def _other_account_in_text(page: PageReading, target: str) -> bool:
    """A line that speaks of an account ("Savings A/C # 1501...") and carries a different
    10+ digit number: the table's number may be another of the holder's accounts (an FDR)."""
    return any(
        _ACCOUNT_WORD.search(ln.text) and len(_digits(run)) >= 10 and _digits(run) != target
        for ln in page.lines
        for run in _LONG_RUN.findall(ln.text)
    )


def _column_number(page: PageReading, labels: Sequence[str], pattern: str) -> Extracted[str] | None:
    """A number under its column header (a details table), scored by exact digit agreement.

    Confident only when PP-OCRv6's line under the header and PaddleOCR-VL's cell under the
    same header give exactly the same digits. A VL column that is unclear, or different
    digits -> DISAGREE. One reader's column alone is never confident (COLUMN_ONE_READER):
    PP-OCRv6's column geometry is fooled by joined or wrapped lines, VL's cells shift when
    it merges or drops one, and the same number elsewhere on the page says nothing about
    which column it was in. Below the threshold the rules engine FLAGs; it never FAILs.
    """
    line = _column_line(page, labels, pattern)
    status, cell = _column_cell(page, labels, pattern)
    if line is not None and parse_date(line.text) is not None:
        line = None  # an Open Date cell, not an account number
    if cell is not None and parse_date(cell) is not None:
        status, cell = "unclear", None
    if status == "tx":
        return None  # VL saw the header in a transaction table: whatever PP-OCRv6 found is too
    if line is not None:
        value = _compact(clean_value(line.text))
        target = _digits(value)
        if status == "value" and _other_account_in_text(page, target):
            conf = DISAGREE  # the letter names another account: which one is the holder's?
        elif status == "value":
            conf = min(line.score, AGREE_CAP) if _digits(cell or "") == target else DISAGREE
        elif status == "unclear" or _near_number(target, page.block_text):
            conf = DISAGREE
        else:
            conf = COLUMN_ONE_READER
        return Extracted[str](value=value, confidence=round(min(conf, FALLBACK_MAX), 4), source_page=page.page_no)
    if status == "value" and cell is not None:
        target = _digits(cell)
        conf = DISAGREE if any(_near_number(target, ln.text) for ln in page.lines) else COLUMN_ONE_READER
        return Extracted[str](value=cell, confidence=round(min(conf, FALLBACK_MAX), 4), source_page=page.page_no)
    return None


def _line_found(page: PageReading, value: str) -> Found | None:
    """Score a value taken from a VL table by finding it among PP-OCRv6's lines."""
    target = squash(value)
    if not target:
        return None
    for ln in page.lines:
        if target in squash(ln.text):
            return Found(value, ln.score, page.page_no)
    return None


def _table_field(page: PageReading, value: str) -> Extracted[str]:
    """A value read from a VL table, confirmed word by word by PP-OCRv6's lines.

    Table cells wrap over several PP-OCRv6 lines ("KAMAL UDDIN" / "S/O: ABDUL" / "KARIM&"), so
    each word is looked up on its own; every word found -> the weakest line's score.
    """
    value = clean_value(re.sub(r"(?<=[A-Za-z])(?=[SDW]/O\b)", " ", value))  # "UDDINS/O" -> "UDDIN S/O"
    if not value:
        return Extracted[str]()
    found = _line_found(page, value)
    if found is not None:
        return Extracted[str](value=value, confidence=round(min(found.score, AGREE_CAP), 4), source_page=page.page_no)
    scores = []
    for word in re.findall(r"[A-Za-z0-9]{2,}", value):
        hit = [ln.score for ln in page.lines if squash(word) in squash(ln.text)]
        if not hit:
            return Extracted[str](value=value, confidence=VL_ONLY, source_page=page.page_no)
        scores.append(max(hit))
    conf = min(min(scores), AGREE_CAP) if scores else VL_ONLY
    return Extracted[str](value=value, confidence=round(conf, 4), source_page=page.page_no)


# --- identity ----------------------------------------------------------------------------


def passport(group: PageGroup, doc_id: str) -> m.Passport:
    mrz = _mrz(group)
    # Labels are bilingual ("<Bangla>/Surname"); OCR often garbles them ("/Suame").
    surname = _name(group, [r"Surname", r"/\s*Su\w{0,3}me\b"])
    given = _name(group, [r"Given\s*Names?"])
    # Always read the printed expiry, MRZ or not: PASSPORT-01 compares it with the MRZ's.
    # Bilingual garbled labels ("craaacf afiky/Date of Expiry") still contain the English part.
    printed_expiry = _date(group, [r"Date\s*of\s*Expiry"])
    fields: dict = {}
    if mrz is not None:
        page_no = _mrz_page(group, mrz)
        ok_name = derived(mrz.surname or None, MRZ_VALID if mrz.valid else MRZ_INVALID, page_no)
        fields = {
            "passport_number": derived(mrz.document_number or None, _mrz_conf(mrz, "document_number"), page_no),
            "mrz_surname": ok_name,
            "mrz_given_names": derived(mrz.given_names or None, MRZ_VALID if mrz.valid else MRZ_INVALID, page_no),
            "date_of_birth": date_field(mrz.birth_date, _mrz_conf(mrz, "birth_date"), page_no),
            "date_of_expiry": date_field(mrz.expiry_date, _mrz_conf(mrz, "expiry_date"), page_no),
        }
        surname = _agree_with_mrz(surname, mrz.surname)
        given = _agree_with_mrz(given, mrz.given_names)
    else:
        fields = {
            "passport_number": _text(group, [r"Passport\s*No\.?", r"Passport\s*Number"], r"[A-Z]{1,2}\d{7,8}"),
            "date_of_birth": _date(group, [r"Date\s*of\s*Birth"]),
            "date_of_expiry": printed_expiry,
        }
    return m.Passport(
        doc_id=doc_id,
        pages=group.page_nos,
        surname=surname,
        given_names=given,
        printed_date_of_expiry=printed_expiry,
        father_name=_name(group, [r"Father'?s?\s*Name"]),
        mother_name=_name(group, [r"Mother'?s?\s*Name"]),
        **fields,
    )


NID_NUMBER = r"\d[\d ]{8,20}\d"
NID_LABELS = [r"NID\s*(?:No|Number)\.?", r"ID\s*NO\.?", r"National\s*ID\s*(?:No|Number)\.?", r"Smart\s*Card\s*No\.?"]


def nid(group: PageGroup, doc_id: str) -> m.NationalId:
    mrz = _mrz(group)
    translation = _translation_pages(group)
    card_pages = [p for p in group.pages if p not in translation] or group.pages
    name = _name(group, [OWN_NAME], pages=card_pages)
    if name.value is None:
        name = _name(group, [OWN_NAME])
    if mrz is not None:
        page_no = _mrz_page(group, mrz)
        name = _agree_with_mrz(name, mrz.full_name)
        if name.confidence < AGREE_CAP:  # e.g. a stamp's text taken for the name on the card copy
            whole = _agree_with_mrz(_name(group, [OWN_NAME]), mrz.full_name)
            name = whole if whole.confidence >= AGREE_CAP else name
        number_on_card = derived(mrz.document_number or None, _mrz_conf(mrz, "document_number"), page_no)
        dob = date_field(mrz.birth_date, _mrz_conf(mrz, "birth_date"), page_no)
    else:
        number_on_card = _text(group, NID_LABELS, NID_NUMBER, pages=card_pages)
        dob = _date(group, [r"Date\s*of\s*Birth"], pages=card_pages)
    number_on_translation = _text(group, NID_LABELS, NID_NUMBER, pages=translation) if translation else Extracted[str]()
    return m.NationalId(
        doc_id=doc_id,
        pages=group.page_nos,
        variant=m.NidVariant.DIGITAL if mrz is not None and mrz.format == "TD1" else m.NidVariant.OLD,
        cardholder_name=name,
        date_of_birth=dob,
        number_on_card=number_on_card,
        number_on_translation=number_on_translation,
        has_english_translation=_nid_has_translation(group, translation),
        notary=_notary(group),
    )


# "BR Number" on older City Corporation certificates (BDR Form-3). The value is 16-20
# digits, possibly one per box with spaces between ("2 0 0 6 ..."), and is never cut out of
# a longer run of digits.
# Never a parent's field ("Father's BR No.", "Mother's Birth Registration No"): if the
# child's own boxes don't read, the lookup must not move on to the parent's number.
_NOT_PARENT = "".join(f"(?<!{p} )" for p in ("Father's", "Fathers", "Father", "Mother's", "Mothers", "Mother", "Parent's", "Parents"))
BRN_LABELS = [
    _NOT_PARENT + r"Birth\s*Registration\s*(?:Number|No)\.?",
    _NOT_PARENT + r"(?<!Birth )Registration\s*No\.?",
    _NOT_PARENT + r"BRN?\s*(?:\w{0,3}umber|No)\.?",  # also OCR slips such as 'BRNMiumber'
]
BRN_VALUE = r"\d(?:\s?\d){15,16}(?!\s?\d)"  # exactly 16-17 digits, never cut from a longer run
# The lookup as before these forms were added, tried first and unchanged.
_BRN_LABELS_V1 = [r"Birth\s*Registration\s*(?:Number|No)\.?", r"Registration\s*No\.?"]
_BRN_VALUE_V1 = r"\d[\d ]{15,20}\d"


def _registration_number(group: PageGroup, pages: Sequence[PageReading]) -> Extracted[str]:
    # BDRIS: the number centred right under its "Birth Registration Number" heading, with
    # "Date of Issuance" beside the heading and stamp text to the left read first.
    for p in pages:
        hit = line_under(p, r"^\W*Birth\s*Registration\s*Number\W*$")
        if hit and re.fullmatch(BRN_VALUE, hit[1].text.strip()):
            label, value = hit
            return text_field(Found(_compact(value.text), min(label.score, value.score), p.page_no), p)
    brn = _text(group, _BRN_LABELS_V1, _BRN_VALUE_V1, pages=pages)
    if brn.value is not None:
        return brn
    # The child's own field is printed first, above the parents'. Only that first label is
    # used, and only if nothing on its line or row names a parent; the lookup never moves on
    # to a later label (a parent's "BR No", a parents' grid row) when the child's boxes fail.
    # PP-OCRv6's lines only: PaddleOCR-VL's text still holds the parents' fields.
    for p in pages:
        lines = reading_order(p.lines)
        first = next((ln for ln in lines if _ANY_BRN_LABEL.search(_plain(ln.text))), None)
        if first is None:
            continue
        row = [first, *(o for o in lines if o is not first and same_row(first, o))]
        if any(_PARENT_WORD.search(_plain(o.text)) for o in row):
            return Extracted[str]()
        # The child's label line and the boxes after it on its row: never a line below (the
        # parents' numbers follow there).
        found = find_labeled(_label_row_only(p, _ANY_BRN_LABEL), BRN_LABELS, value_pattern=BRN_VALUE)
        if found is None:
            return Extracted[str]()
        brn = text_field(Found(_compact(found.value), found.score, found.page_no), p)
        return brn.model_copy(update={"confidence": min(brn.confidence, FALLBACK_MAX)})
    return Extracted[str]()


# Any registration-number label, a parent's included (to find and set aside the parents').
_ANY_BRN_LABEL = re.compile(r"Birth\s*Registration\s*(?:Number|No)|Registration\s*No|\bBRN?\s*(?:\w{0,3}umber|No)\b", re.IGNORECASE)


_IN_WORDS = re.compile(r"\bIn\s*Words?\s*[:：\-]?\s*(.+)$", re.IGNORECASE)
_IN_WORDS_LABEL = re.compile(r"In\s*Words?\s*[:：\-]?", re.IGNORECASE)
# A date of birth read only from the "In Word" line is evidence for the reviewer, never
# confident: wrapped, misspelt or partly read words still parse to a valid, different date
# ("Two Thousand / Six" -> 2000), and nothing else on the page confirms it.
IN_WORDS_MAX = VL_ONLY
# The next field's label on the same line. Known words only: a pattern for "any words before
# a colon" would cut "... Two Thousand One  Date of ...:" after "Two Thousand" (year 2000).
_NEXT_FIELD = re.compile(
    r"\s+(?=(?:Date|Sex|Gender|Order|Place|Registration|Register|Issue|Issuance|Issued|Father|Mother|Name|Permanent|Address|BRN?|NID)\b[^:：]{0,30}[:：])",
    re.IGNORECASE,
)
_STARTS_WITH_LABEL = re.compile(r"[A-Za-z][A-Za-z.' ]{0,30}[:：]")


_DOB_LABEL = re.compile(r"Date\s*of\s*Birth", re.IGNORECASE)
_PARENT_WORD = re.compile(r"\b(?:Father|Mother|Parent)", re.IGNORECASE)


def _plain(text: str) -> str:
    return re.sub(r"[’‘`´]", "'", text)


def _label_row_only(page: PageReading, label: re.Pattern[str]) -> PageReading:
    """The page cut down to the first line carrying `label` and the boxes after it on its
    row, up to the next field (a box with letters in it: "Date of Registration:", a
    second column). A value looked up there can't come from another field. PaddleOCR-VL's
    text is left out too: a lookup falling back to it would search the whole page again."""
    lines = reading_order(page.lines)
    first = next((ln for ln in lines if label.search(_plain(ln.text))), None)
    if first is None:
        return page.model_copy(update={"lines": (), "blocks": ()})
    keep = [first]
    for o in sorted((o for o in lines if o is not first and same_row(first, o) and o.box[0] >= first.box[2] - 10), key=lambda o: o.box[0]):
        if re.search(r"[A-Za-z]", o.text):
            break
        keep.append(o)
    return page.model_copy(update={"lines": tuple(keep), "blocks": ()})


def _birth_date(group: PageGroup, pages: Sequence[PageReading]) -> Extracted[date]:
    """'Date of Birth' (also one digit per box); else the certificate's own 'In Word: 8th
    May, 2006' / 'In Word: Fifth August Two Thousand One' line. Only that line: the lines
    near it are other dates (registration, issue)."""
    dob = _date(group, [r"Date\s*of\s*Birth"], pages=pages)
    if dob.value is not None:
        return dob
    boxed = _date(group, [r"Date\s*of\s*Birth"], pages=[_label_row_only(p, _DOB_LABEL) for p in pages], boxed=True)
    if boxed.value is not None:
        return boxed.model_copy(update={"confidence": min(boxed.confidence, FALLBACK_MAX)})
    for page in pages:
        for ln in page.lines:
            mt = _IN_WORDS.search(ln.text)
            score = ln.score
            if mt and not _IN_WORDS_LABEL.fullmatch(ln.text.strip()):
                value = clean_value(mt.group(1))
            elif _IN_WORDS_LABEL.fullmatch(ln.text.strip()):
                # The label in a box of its own: its value is the nearest box to its right on
                # the same row. Further right is the certificate's other column.
                right = sorted((o for o in page.lines if o is not ln and o.box[0] >= ln.box[2] - 10 and same_row(ln, o)), key=lambda o: o.box[0])
                if not right or right[0].box[0] - ln.box[2] > ROW_FIRST_GAP_PX:
                    continue
                value, score = clean_value(right[0].text), min(ln.score, right[0].score)
            else:
                continue
            if _STARTS_WITH_LABEL.match(value):
                continue  # another field's box ("Date of Issuance: ..."), not this one's value
            # Stop at the next field on the same line ("... Date of Registration: 12/09/2001").
            value = _NEXT_FIELD.split(value, maxsplit=1)[0].strip()
            value = value.replace("ß", "B")  # OCR reads a small-print 'b' as 'ß' ('25th feß, 2002')
            if not has_month_name(value):
                continue  # a date in words always names its month
            numeric, words = (parse_date(value), parse_words_date(value)) if value else (None, None)
            if numeric and words and numeric != words:
                continue  # two different dates: not chosen between
            d = numeric or words
            if d is not None:
                conf = min(score_text(Found(value, score, page.page_no), page), IN_WORDS_MAX)
                return date_field(d, conf, page.page_no)
    return dob


# Case-sensitive "Father": an all-caps "FATHER" is a relation cell in a family table.
_BARE_PARENT = r"\b(?-i:{})\b(?!'|’|\s*s\b|\s*(?:Name|Nationality|NID|BRN))"


def birth_certificate(group: PageGroup, doc_id: str) -> m.BirthCertificate:
    english = [p for p in group.pages if page_language(p).value == "ENGLISH"] or group.pages
    return m.BirthCertificate(
        doc_id=doc_id,
        pages=group.page_nos,
        registration_number=_registration_number(group, english),
        name=_name(group, [r"Name\s*of\s*(?:the\s*)?Child", OWN_NAME], pages=english),
        date_of_birth=_birth_date(group, english),
        # Small print on old forms reads as 'Fathar's' / 'Motfiar's': a few letters may differ.
        # The bilingual BDRIS form prints a bare "Father :" / "Mother :" (not "Father's Nationality").
        father_name=_name(group, [r"\bFa[a-z]{2,3}r'?s?\s*Name", _BARE_PARENT.format("Father")], pages=english),
        mother_name=_name(group, [r"\bMo[a-z]{2,4}r'?s?\s*Name", _BARE_PARENT.format("Mother")], pages=english),
        language=document_language(group.pages),
        has_english_translation=has_translation(group.pages),
        notary=_notary(group),
    )


def death_certificate(group: PageGroup, doc_id: str) -> m.DeathCertificate:
    return m.DeathCertificate(
        doc_id=doc_id,
        pages=group.page_nos,
        registration_number=_text(group, [r"Death\s*Registration\s*(?:Number|No)\.?", r"Registration\s*No\.?"], r"\d[\d ]{8,20}\d"),
        deceased_name=_name(group, [r"Name\s*of\s*(?:the\s*)?Deceased", r"Deceased'?s?\s*Name", OWN_NAME]),
        date_of_death=_date(group, [r"Date\s*of\s*Death"]),
        language=document_language(group.pages),
        has_english_translation=has_translation(group.pages),
        notary=_notary(group),
    )


_RELATION_WORDS = ("SELF", "HIMSELF", "HERSELF", "APPLICANT", "FATHER", "MOTHER", "BROTHER", "SISTER", "SON", "DAUGHTER", "WIFE", "HUSBAND", "SPOUSE")


_SELF_WORDS = {"SELF", "HERSELF", "HIMSELF", "APPLICANT"}
_ROW_RELATIONS = _SELF_WORDS | {"FATHER", "MOTHER"}


def _relation_key(text: str | None) -> str:
    return re.sub(r"[^A-Z]", "", (text or "").upper())


def _rows_the_table_reader_missed(group: PageGroup, members: list[m.FrcMember]) -> list[m.FrcMember]:
    """The layout reader sometimes returns only the first rows of a family table. A relation
    cell ('FATHER') that the line reader saw but no table row holds becomes a row whose
    relation is unreadable, so the rules FLAG it for a person instead of FAILing 'no FATHER
    row'. Column headers ('FATHER' as a heading beside 'RELATION') are not cells."""
    from collections import Counter

    seen: Counter[str] = Counter()
    for page in group.pages:
        headers = [ln for ln in page.lines if re.search(r"RELATION", ln.text, re.IGNORECASE)]
        for ln in page.lines:
            key = _relation_key(ln.text)
            if key in _ROW_RELATIONS and re.fullmatch(r"[A-Za-z]+", ln.text.strip()) and not any(same_row(ln, h) for h in headers):
                seen[key] += 1
    have = Counter(_relation_key(mb.relation.value) for mb in members)
    missed = [key for key, n in seen.items() for _ in range(n - have[key])]
    return [m.FrcMember(relation=Extracted[str](value=key, confidence=VL_ONLY)) for key in missed]


# Some councils put the member's ID in the name cell: "RIAD HASAN APU. NID NO: 8729747587",
# "MD MEHRAB SIAM. DOB-2005...". The name is what comes before it.
_CELL_ID = re.compile(r"[.,;]?\s*\b(?:NID|DOB|D\.O\.B|BRN|BIRTH\s*REG(?:ISTRATION)?)\b.*$", re.IGNORECASE | re.DOTALL)


def frc(group: PageGroup, doc_id: str) -> m.FamilyRelationshipCertificate:
    from .classify import SIG

    issuer_found = None
    for page in group.pages:
        for ln in reading_order(page.lines):
            if SIG["frc_issuer"].search(ln.text):
                issuer_found = (Found(clean_value(ln.text), ln.score, page.page_no), page)
                break
        if issuer_found:
            break
    members: list[m.FrcMember] = []
    for page in group.pages:
        for table in _tables(page):
            header = [c.upper() for c in table[0]] if table else []
            name_col = next((i for i, c in enumerate(header) if "NAME" in c), None)
            rel_col = next((i for i, c in enumerate(header) if "RELATION" in c), None)
            dob_col = next((i for i, c in enumerate(header) if "BIRTH" in c or "DOB" in c), None)
            if name_col is None or rel_col is None:
                continue
            for row in table[1:]:
                if len(row) <= max(name_col, rel_col):
                    continue
                dob = parse_date(row[dob_col]) if dob_col is not None and dob_col < len(row) else None
                members.append(
                    m.FrcMember(
                        name=_table_field(page, _CELL_ID.sub("", row[name_col])),
                        relation=_table_field(page, row[rel_col]),
                        date_of_birth=date_field(dob, _table_field(page, row[dob_col]).confidence, page.page_no) if dob else Extracted[date](),
                    )
                )
    members += _rows_the_table_reader_missed(group, members)
    if not any(_relation_key(mb.relation.value) in _SELF_WORDS for mb in members):
        # Some councils name the applicant under the table instead of in a SELF row.
        applicant, page = _first(group, lambda p: find_labeled(p, [r"Applicant'?s?\s*Name"], value_pattern=NAME, stop_words=NAME_STOPS))
        if applicant is not None:
            # The relation is implied by the printed label, not read from a cell: as sure as the label line.
            relation = Extracted[str](value="APPLICANT", confidence=round(min(applicant.score, AGREE_CAP), 4), source_page=applicant.page_no)
            members.append(m.FrcMember(name=text_field(applicant, page), relation=relation))
    issue_date = _date(group, [r"Date\s*of\s*Issue", r"Issue\s*Date", r"Issued\s*on"])
    if issue_date.value is None:
        # Letter-style header: "Ref: ABC/1/2026  Date: 01-10-2026" (first "Date", top of page).
        issue_date = _date(group, [r"\bDate\b(?!\s*of)"])
    return m.FamilyRelationshipCertificate(
        doc_id=doc_id,
        pages=group.page_nos,
        issuer_text=text_field(*issuer_found) if issuer_found else Extracted[str](),
        members=tuple(members),
        issue_date=issue_date,
        registration_date=_date(group, [r"Date\s*of\s*Registration", r"Registration\s*Date"]),
        notary=_notary(group),
        late_names=_late_names(group),
    )


# "son of Late Md Abdur Razzak & Rajea Akter": the capitalised name after "Late", up to "&"/"and"/",".
_LATE = re.compile(r"(?i:\bLATE)\s+((?:[A-Z][A-Za-z.']*\s*){1,6}?)(?=\s*(?:&|(?i:\bAND\b|\bOF\b|\bIS\b)|,|\(|$))")


def _late_names(group: PageGroup) -> tuple[Extracted[str], ...]:
    names = []
    for page in group.pages:
        lines = reading_order(page.lines)
        text, starts = "", []
        for ln in lines:
            starts.append(len(text))
            text += ln.text + " "
        for mt in _LATE.finditer(text):
            name = clean_value(mt.group(1))
            # the lines the match runs over
            used = [ln for ln, a in zip(lines, starts, strict=True) if a < mt.end() and a + len(ln.text) > mt.start()]
            if name and used:
                names.append(text_field(Found(name, min(ln.score for ln in used), page.page_no), page))
    return tuple(names)


_PERSON_OF = (
    (re.compile(r"\bMOTHER", re.IGNORECASE), Person.MOTHER),
    (re.compile(r"\bFATHER", re.IGNORECASE), Person.FATHER),
    (re.compile(r"\bMY\s+NAME\b|\bOWN\s+NAME\b|\bSELF\b", re.IGNORECASE), Person.STUDENT),
)


def _person(text: str) -> Person | None:
    for rx, person in _PERSON_OF:
        if rx.search(text):
            return person
    return None


def affidavit(group: PageGroup, doc_id: str) -> m.Affidavit:
    deponent = None
    for page in group.pages:
        for ln in reading_order(page.lines):
            mt = re.search(r"\bI\s*,\s*([A-Za-z][A-Za-z .\-']{1,60}?)\s*,", ln.text)
            if mt:
                deponent = (Found(clean_value(mt.group(1)), ln.score, page.page_no), page)
                break
        if deponent:
            break
    same = [(p, ln) for p in group.pages for ln in p.lines if re.search(r"SAME\s+PERSON", ln.text, re.IGNORECASE)]
    states_same = (
        Extracted[bool](value=True, confidence=round(min(max(ln.score for _, ln in same), AGREE_CAP), 4), source_page=same[0][0].page_no)
        if same
        else Extracted[bool]()  # absent phrase: unknown (FLAG), never a confident "no"
    )
    # Two tables: names as written in some documents, then the different spelling elsewhere.
    tables = [(page, t) for page in group.pages for t in _tables(page)]
    by_person: dict[Person, dict[str, Extracted[str]]] = {}
    for idx, (page, table) in enumerate(tables[:2]):
        slot = "existing_name" if idx == 0 else "different_name"
        for row in table:
            if len(row) < 2:
                continue
            person = _person(row[-1]) or _person(" ".join(row))
            if person is None:
                continue
            name_cell = next((c for c in reversed(row[:-1]) if re.fullmatch(NAME, c or "") and _person(c) is None and "DOCUMENT" not in c.upper()), None)
            if name_cell:
                by_person.setdefault(person, {})[slot] = _table_field(page, name_cell)
    entries = tuple(
        m.AffidavitEntry(person=p, existing_name=v.get("existing_name", Extracted[str]()), different_name=v.get("different_name", Extracted[str]()))
        for p, v in by_person.items()
    )
    return m.Affidavit(
        doc_id=doc_id,
        pages=group.page_nos,
        deponent_name=text_field(*deponent) if deponent else Extracted[str](),
        states_same_person=states_same,
        entries=entries,
        notary=_notary(group),
    )


# --- financial ---------------------------------------------------------------------------

ACCOUNT_NO = r"[0-9][0-9 \-]{5,24}[0-9]"
ACCOUNT_LABELS = [r"A/?C\.?\s*(?:No|Number)\.?", r"Account\s*(?:No|Number)\.?"]


_ACCOUNT_FIELD = re.compile(
    r"(?:^|\b)(?:" + "|".join(ACCOUNT_LABELS) + r")\s*"
    r"(?:[:：]\s*(?![\d\s\-]{6,})[^\s\d]|[:：\-.]?\s*(?=[\dXx*•\s\-]*[Xx*•]{3})[\dXx*•][\dXx*•\s\-]{4,})",
    re.IGNORECASE,
)


def _account_field_unreadable(group: PageGroup) -> bool:
    """'Account No: XXXXXXXX7001' (masked) or 'A/C No: <unreadable>': the holder's number is
    printed as a field but could not be read. Then a number from some table on the page
    is not taken instead (it may be another account); the field stays empty: FLAG."""
    texts = [ln.text for p in group.pages for ln in p.lines] + [
        t for p in group.pages for t in p.block_text.splitlines()
    ]
    return any(_ACCOUNT_FIELD.search(re.sub(r"<[^>]+>", " ", t)) for t in texts)


def _account_number(group: PageGroup) -> Extracted[str]:
    """The labelled lookup exactly as before ('A/C No: 0123...', the number beside or under
    the label), except that a date ("05-10-2026", an Open Date cell under a header row) is
    never an account number.

    Only when that finds nothing, and the holder's field is not printed masked or
    unreadable, a details table with an 'Account Number' column header is read; there only
    both readers agreeing under that header is confident (_column_number).
    """
    found, page = _first(group, lambda p: find_labeled(p, ACCOUNT_LABELS, value_pattern=ACCOUNT_NO))
    if found is not None and page is not None and not _WHOLE_DATE.fullmatch(clean_value(found.value)):
        return text_field(Found(_compact(found.value), found.score, found.page_no), page)
    if _account_field_unreadable(group):
        return Extracted[str]()
    for p in group.pages:
        column = _column_number(p, ACCOUNT_LABELS, ACCOUNT_NO)
        if column is not None:
            return column
    return Extracted[str]()


def _holder_from_sentence(group: PageGroup) -> Extracted[str]:
    """'This is to certify that ABDUL KARIM, Son of ...' -> ABDUL KARIM.

    Courtesy titles (Mr, Mrs, Ms) are dropped; 'Md' / 'Mst' are kept, because they are
    part of the name: the name policy (hklv_rules.names) reads 'MD X' and 'X' as
    different names, so 'Md Kamal Uddin' stripped to 'Kamal Uddin' would not match a
    father recorded as 'MD KAMAL UDDIN'."""
    rx = re.compile(r"certify\s+that\s+(?:(?:Mrs|Mr|Ms)\b\.?)?\s*([A-Za-z][A-Za-z .\-']{1,60}?)\s*(?:,|\bS/O\b|\bD/O\b|\bW/O\b|\bson\b|\bdaughter\b|\bwife\b|\bmaintain|\bhas\b|\bis\b)", re.IGNORECASE)
    for page in group.pages:
        lines = reading_order(page.lines)
        for i, ln in enumerate(lines):
            joined = ln.text + (" " + lines[i + 1].text if i + 1 < len(lines) else "")
            mt = rx.search(joined)
            if mt:
                return text_field(Found(clean_value(mt.group(1)), ln.score, page.page_no), page)
    return Extracted[str]()


# money, not a row number or year: grouped digits, decimals, or 5+ digits; never a rate's
# digits ('USD@124.50 BDT')
_AMT = r"(?<![@\d.,])(?:\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+\.\d{2}|\d{5,})(?![\d,])"
_USD_WORD = r"\bUSD\b|\bUS\s*\$|\$|\bUS\s*Dollars?\b"
_BDT_WORD = r"\bBDT\b|\bTk\b|\bTaka\b"
# currency then amount ('USD 19,338.09'), else amount then currency, but not a rate
# ('1 USD = 123.70')
_USD_AMOUNT = (
    re.compile(rf"(?:{_USD_WORD})\s*[:.,]?\s*{_AMT}", re.IGNORECASE),
    re.compile(rf"{_AMT}\s*(?:{_USD_WORD})(?!\s*=)", re.IGNORECASE),
)
_BDT_AMOUNT = (
    re.compile(rf"(?:{_BDT_WORD})\s*[:.,]?\s*{_AMT}", re.IGNORECASE),
    re.compile(rf"{_AMT}\s*/?-?\s*(?:{_BDT_WORD})(?!\s*=)", re.IGNORECASE),
)
_RATE = re.compile(r"=|@|\bRATE\b", re.IGNORECASE)
_CELL_AMOUNT = re.compile(rf"\W*{_AMT}")  # a cell that starts with the amount ('20191.88(Approximately)')


def _amount_under_header(page: PageReading, word: str) -> TextLine | None:
    """A table column headed by the currency ('Balance (USD)') with an amount below it."""
    word_re = re.compile(word, re.IGNORECASE)
    for h in page.lines:
        if not word_re.search(h.text) or _RATE.search(h.text):
            continue
        below = [
            o for o in page.lines
            if o.box[1] >= h.box[3] - 5 and min(o.box[2], h.box[2]) > max(o.box[0], h.box[0]) and _CELL_AMOUNT.match(o.text)
        ]
        if below:
            return min(below, key=lambda o: o.box[1])
    return None


def _amount_shown(group: PageGroup, patterns: tuple[re.Pattern[str], ...], word: str) -> Extracted[str]:
    """The first amount in that currency, from either reader: written next to the currency,
    or in a column headed by it. Only its presence is checked (BANK-05), so where it was
    found matters, not how surely it was read."""
    for p in group.pages:
        lines = " ".join(ln.text for ln in reading_order(p.lines))
        vl = html.unescape(re.sub(r"<[^>]+>", " ", p.block_text))
        for rx in patterns:
            for text, conf in ((lines, AGREE_CAP), (vl, VL_ONLY)):
                if mt := rx.search(text):
                    return derived(clean_value(mt.group(0)), conf, p.page_no)
        if cell := _amount_under_header(p, word):
            return derived(clean_value(cell.text), cell.score, p.page_no)
    return Extracted[str]()


# Board registration 'No. 1910534278/2022-23' (or '/2015', '/2017-2018'): the number, then the session. Only the
# number is kept: SSC and HSC share it, their sessions differ (ACAD-06).
_BOARD_REGISTRATION = re.compile(r"(?<!\d)(\d{6,12})\s*/\s*(?:19|20)\d{2}(?:\s*-\s*\d{2,4})?(?!\d)")


def _board_registration(group: PageGroup) -> Extracted[str]:
    for p in group.pages:
        for ln in reading_order(p.lines):
            if mt := _BOARD_REGISTRATION.search(ln.text):
                return text_field(Found(mt.group(1), ln.score, p.page_no), p)
    return Extracted[str]()


def bank_solvency(group: PageGroup, doc_id: str) -> m.BankSolvency:
    # The letter's own sentence first; its details table has column headers ("Name of
    # Account | Account Number | Balance") that a label search would read as the value.
    holder = _holder_from_sentence(group)
    if holder.value is None:
        holder = _name(group, [r"Account\s*Holder(?:'s)?\s*(?:Name)?", r"A/?C\s*Name"])
    return m.BankSolvency(
        doc_id=doc_id,
        pages=group.page_nos,
        account_holder=holder,
        account_number=_account_number(group),
        letter_date=_date(group, LETTER_DATE),
        usd_amount=_amount_shown(group, _USD_AMOUNT, _USD_WORD),
        bdt_amount=_amount_shown(group, _BDT_AMOUNT, _BDT_WORD),
    )


def bank_statement(group: PageGroup, doc_id: str) -> m.BankStatement:
    return m.BankStatement(
        doc_id=doc_id,
        pages=group.page_nos,
        account_holder=_name(group, [r"Account\s*Name", r"A/?C\s*Name", r"Customer\s*Name", r"Account\s*Holder", OWN_NAME]),
        account_number=_account_number(group),
        statement_date=_date(group, [r"Generation\s*Date", r"Generated\s*(?:on|Date)", r"As\s*on", r"Print(?:ing)?\s*Date", r"Printed\s*on", r"Statement\s*Date"]),
    )


# 'Valid up to 30 June 2027', 'valid till June 30, 2027', 'Date of Validity : 30-06-2027',
# 'Validity of this trade license 1st July 2026 to 30th June 2027'
_VALIDITY = re.compile(r"\bVALID|\bTILL\b|\bUP\s*TO\b", re.IGNORECASE)
_FY_WORDS = re.compile(r"\b(?:FISCAL|FINANCIAL|FINANCE|ASSESSMENT)\s*YEAR\b|\bTENURE\b|\bTERM\b", re.IGNORECASE)
_FY_VALUE = re.compile(r"(20\d{2})\s*[-–/]\s*((?:20)?\d{2})(?!\d)")


def _latest_dated(group: PageGroup, pages: Sequence[PageReading], line_re: re.Pattern[str]) -> Extracted[date]:
    """The latest date on any line matching `line_re` (a renewal page lists every year)."""
    best: tuple[date, Found, PageReading] | None = None
    for p in pages:
        for ln in p.lines:
            ds = [d for d in find_dates(ln.text) if d.year >= 2000] if line_re.search(ln.text) else []  # not '20251' -> 0251
            if ds:
                if best is None or max(ds) > best[0]:
                    best = (max(ds), Found(ln.text, ln.score, p.page_no), p)
    if best is None:
        return Extracted[date]()
    return date_field(best[0], score_text(best[1], best[2]), best[1].page_no)


def _fiscal_year_line(pages: Sequence[PageReading]) -> tuple[Found, PageReading] | None:
    """'Tenure: 2025-2026 Financial Year', 'Term 2026-2027 fiscal year': the latest year
    printed on a line that names it."""
    best = None
    for p in pages:
        for ln in p.lines:
            if not _FY_WORDS.search(ln.text):
                continue
            for a, b in _FY_VALUE.findall(ln.text):
                end = b if len(b) == 4 else a[:2] + b
                if best is None or (a, end) > best[0]:
                    best = ((a, end), Found(f"{a}-{end}", ln.score, p.page_no), p)
    return (best[1], best[2]) if best else None


def trade_license(group: PageGroup, doc_id: str) -> m.TradeLicense:
    english = [p for p in group.pages if page_language(p).value == "ENGLISH"] or group.pages
    fy = None
    found, page = _first(
        group,
        lambda p: find_labeled(p, [r"Fiscal\s*Year", r"Financial\s*Year", r"Assessment\s*Year", r"F\.\s?Y\.?"], value_pattern=r"20\d{2}\s*[-–/]\s*(?:20)?\d{2}"),
        english,
    )
    if found is not None:
        mt = re.match(r"(20\d{2})\s*[-–/]\s*((?:20)?\d{2})", found.value)
        end = mt.group(2) if len(mt.group(2)) == 4 else mt.group(1)[:2] + mt.group(2)
        fy = (Found(f"{mt.group(1)}-{end}", found.score, found.page_no), page)
    elif (line_fy := _fiscal_year_line(english)) is not None:
        fy = line_fy
    return m.TradeLicense(
        doc_id=doc_id,
        pages=group.page_nos,
        license_number=_text(group, [r"Licen[cs]e\s*(?:No|Number)\.?", r"Trade\s*Licen[cs]e\s*(?:No|Number)\.?"], r"[A-Z0-9/\-]*\d{6,}[A-Z0-9/\-]*", pages=english),
        owner_name=_name(group, [r"Name\s*of\s*(?:the\s*)?(?:Proprietor|Owner)(?:\s*/\s*Assessee)?", r"Proprietor'?s?\s*Name", r"Owner'?s?\s*Name", r"Name\s*of\s*Licen[cs]es?\s*Holder"], pages=english),
        fiscal_year=text_field(*fy) if fy else Extracted[str](),
        valid_until=_latest_dated(group, english, _VALIDITY),
        issue_date=_date(group, [r"Date\s*of\s*Issue", r"Issue\s*Date"], pages=english),
        language=document_language(group.pages),
        has_english_translation=has_translation(group.pages),
        notary=_notary(group),
    )


# Present tense only: "was working" / "served" is an experience or release letter (EMP-04 FAIL).
_EMPLOYED_NOW = re.compile(
    r"\bIS\s+(?:WORKING|EMPLOYED|SERVING)\b|\bCURRENTLY\b"
    r"|\bIS\s+AN?\s+(?:\w+\s+){0,2}EMPLOYEE\s+SERVING\b"  # "is a government employee serving at"
    r"|\bCONTINUES\s+TO\s+(?:HOLD|SERVE|WORK)\b",  # "continues to hold the position to date"
    re.IGNORECASE,
)


def employment_certificate(group: PageGroup, doc_id: str) -> m.EmploymentCertificate:
    employed = [(p, ln) for p in group.pages for ln in p.lines if _EMPLOYED_NOW.search(ln.text)]
    return m.EmploymentCertificate(
        doc_id=doc_id,
        pages=group.page_nos,
        employee_name=_holder_from_sentence(group),
        issue_date=_date(group, LETTER_DATE),
        currently_employed=(
            Extracted[bool](value=True, confidence=round(min(employed[0][1].score, AGREE_CAP), 4), source_page=employed[0][0].page_no)
            if employed
            else Extracted[bool]()
        ),
        language=document_language(group.pages),
        has_english_translation=has_translation(group.pages),
        notary=_notary(group),
    )


TIN_RE = re.compile(r"\b(\d{12})\b")


def tin_certificate(group: PageGroup, doc_id: str) -> m.TinCertificate:
    qr = next((b for p in group.pages for b in p.barcodes if b.format.upper().startswith("QR")), None)
    tin_from_qr = None
    if qr is not None:
        mt = re.search(r"TIN\s*(?:No\.?)?\s*[:\-]?\s*(\d{12})", qr.text, re.IGNORECASE) or TIN_RE.search(qr.text)
        tin_from_qr = mt.group(1) if mt else None
    return m.TinCertificate(
        doc_id=doc_id,
        pages=group.page_nos,
        taxpayer_name=_name(group, [r"Taxpayer'?s?\s*Name", OWN_NAME]),
        tin_printed=_text(group, [r"\bTIN\b(?:\s*No\.?)?"], r"\d{12}"),
        qr_decoded=qr is not None,
        tin_from_qr=tin_from_qr,
    )


# An amount, optionally after a currency mark ('Tk. 12,000', 'BDT 15,000.00', '1,00,000/-').
_AMOUNT_VALUE = r"(?:Tk\.?|BDT|Taka|৳)?\s*[\d,]+(?:\.\d{1,2})?(?:\s*/-)?"


def _amount(group: PageGroup, labels: Sequence[str]) -> Extracted[Decimal]:
    found, page = _first(group, lambda p: find_labeled(p, labels, value_pattern=_AMOUNT_VALUE))
    if found is None:
        return Extracted[Decimal]()
    number = re.search(r"\d[\d,]*(?:\.\d{1,2})?", found.value)
    try:
        value = Decimal(number.group(0).replace(",", ""))
    except (AttributeError, InvalidOperation):
        return Extracted[Decimal]()
    return Extracted[Decimal](value=value, confidence=round(score_text(found, page), 4), source_page=found.page_no)


# A-challan number, e.g. '2526-0012345678' (4-digit year code, 10-digit serial).
_ACHALLAN_NO = re.compile(r"(?<!\d)\d{4}\s*-\s*\d{10}(?!\d)")


def tax_challan(group: PageGroup, doc_id: str) -> m.IncomeTaxChallan:
    # The QR carries the challan number checksum-protected; the printed text is the fallback.
    in_qr = next(
        ((mt, p.page_no) for p in group.pages for b in p.barcodes
         if b.format.upper().startswith("QR") and (mt := _ACHALLAN_NO.search(b.text))),
        None,
    )
    if in_qr:
        number = Extracted[str](value=re.sub(r"\s", "", in_qr[0].group(0)), confidence=MRZ_VALID, source_page=in_qr[1])
    else:
        number = _text(group, [r"Challan\s*(?:No|Number)\.?", r"Transaction\s*ID"], r"[A-Z0-9][A-Z0-9\-]{5,30}")
    if not number.found:
        # e-Payment challans label the number in Bangla only: a line that is exactly an A-challan number.
        line = next(((ln, p) for p in group.pages for ln in p.lines if _ACHALLAN_NO.fullmatch(ln.text.strip())), None)
        if line:
            ln, page = line
            number = text_field(Found(re.sub(r"\s", "", ln.text), ln.score, page.page_no), page)
            # The slip prints the number twice; a second line with the same digits confirms it
            # when the layout reader garbled it.
            wanted = re.sub(r"\D", "", ln.text)
            if sum(re.sub(r"\D", "", o.text) == wanted for o in page.lines) >= 2:
                number = number.model_copy(update={"confidence": round(min(ln.score, AGREE_CAP), 4)})
    # 'Total Amount' first; never the line under 'Amount in words'.
    amount = _amount(group, [r"Total\s*Amount", r"Amount(?!\s*in\s*words)", r"Taka(?!\s*in\s*words)"])
    if not amount.found:
        amount = _amount_with_words(group)
    return m.IncomeTaxChallan(doc_id=doc_id, pages=group.page_nos, challan_number=number, printed_amount=amount)


_AMOUNT_AND_WORDS = re.compile(r"(\d[\d,]*(?:\.\d{1,2})?)\s*\(([A-Za-z ]+?Taka\s*Only)\)", re.IGNORECASE)


def _amount_with_words(group: PageGroup) -> Extracted[Decimal]:
    """'3000.00 (Three Thousand Taka Only)' with no English label. Trusted only when the
    digits and the words agree; otherwise it is evidence for the reviewer (FLAG), because a
    misread amount would FAIL TAX-04 against the website."""
    for page in group.pages:
        for ln in page.lines:
            mt = _AMOUNT_AND_WORDS.search(ln.text)
            if not mt:
                continue
            value = Decimal(mt.group(1).replace(",", ""))
            agree = parse_amount_words(mt.group(2)) == value
            conf = min(ln.score, AGREE_CAP) if agree else VL_ONLY
            return Extracted[Decimal](value=value, confidence=round(conf, 4), source_page=page.page_no)
    return Extracted[Decimal]()


def tax_acknowledgement(group: PageGroup, doc_id: str) -> m.IncomeTaxAcknowledgement:
    return m.IncomeTaxAcknowledgement(
        doc_id=doc_id,
        pages=group.page_nos,
        total_tax_paid=_amount(group, [r"Total\s*Tax\s*Paid", r"Tax\s*Paid"]),
        total_income=_amount(group, [r"Total\s*Income(?:\s*Shown)?"]),
    )


def tax_certificate(group: PageGroup, doc_id: str) -> m.IncomeTaxCertificate:
    return m.IncomeTaxCertificate(doc_id=doc_id, pages=group.page_nos, taxpayer_name=_holder_from_sentence(group))


# --- language test (optional) ------------------------------------------------------------


def _cell_under(group: PageGroup, header: str, accept) -> tuple[Found, PageReading] | None:
    """A table header cell matching `header` exactly, and the first line below it that
    overlaps its column and that `accept` takes: the cell under it, not the leftmost value
    of the next row."""
    for page in group.pages:
        for h in page.lines:
            if not re.fullmatch(header, h.text.strip(), re.IGNORECASE):
                continue
            below = sorted(
                (ln for ln in page.lines if 0 < ln.box[1] - h.box[3] < 3 * (h.box[3] - h.box[1]) and ln.box[0] < h.box[2] and ln.box[2] > h.box[0]),
                key=lambda ln: ln.box[1],
            )
            for ln in below:
                if accept(clean_value(ln.text)):
                    return Found(clean_value(ln.text), ln.score, page.page_no), page
    return None


def _name_under(group: PageGroup, header: str) -> Extracted[str]:
    stops = re.compile(r"(?:" + "|".join(NAME_STOPS) + r")\b", re.IGNORECASE)
    cell = _cell_under(group, header, lambda t: bool(re.fullmatch(NAME, t)) and not stops.match(t))
    return text_field(*cell) if cell else Extracted[str]()


def _date_under(group: PageGroup, header: str) -> Extracted[date]:
    cell = _cell_under(group, header, lambda t: parse_date(t) is not None)
    return date_field(parse_date(cell[0].value), score_text(*cell), cell[0].page_no) if cell else Extracted[date]()


def language_test(group: PageGroup, doc_id: str) -> m.LanguageTest:
    """IELTS Test Report Form or TOPIK certificate. Not yet seen on a real sample: labels
    follow the published layouts; anything not found stays empty (rules FLAG it)."""
    text = "\n".join(p.line_text for p in group.pages)
    kind = None
    for name, value in (("IELTS", m.LanguageTestKind.IELTS), ("TOPIK", m.LanguageTestKind.TOPIK)):
        line = next((ln for p in group.pages for ln in p.lines if name in ln.text.upper()), None)
        if line is not None:
            kind = Extracted[m.LanguageTestKind](value=value, confidence=round(min(line.score, AGREE_CAP), 4), source_page=group.pages[0].page_no)
            break
    # IELTS prints the name in two fields; TOPIK in one.
    family = _name(group, [r"Family\s*Name", r"Surname"])
    first = _name(group, [r"First\s*Names?", r"Given\s*Names?"])
    if family.value and first.value:
        name = Extracted[str](
            value=f"{first.value} {family.value}",
            confidence=min(family.confidence, first.confidence),
            source_page=family.source_page,
        )
    else:
        name = _name(group, [r"Candidate'?s?\s*Name", "(?<!Family )(?<!First )" + OWN_NAME])
    if not name.found:
        name = _name_under(group, "Name")  # TOPIK score report: Name | Gender | Country | Date of Birth
    test_date = _date(group, [r"Test\s*Date", r"Date\s*of\s*Test", r"Date\s*of\s*(?:Issue|Exam(?:ination)?)", r"Issue\s*Date"])
    if test_date.value is None and "IELTS" in text.upper():
        test_date = _date(group, [r"(?<!of )\bDate\b(?!\s*of)"])  # IELTS TRF header: "Date 12/OCT/2026"
    if test_date.value is None:
        test_date = _date_under(group, r"Test\s*Held\s*/\s*Test\s*Date|Test\s*Date")
    dob = _date(group, [r"Date\s*of\s*Birth", r"Birth\s*Date"])
    if dob.value is None:
        dob = _date_under(group, r"Date\s*of\s*Birth")
    return m.LanguageTest(
        doc_id=doc_id,
        pages=group.page_nos,
        test=kind or Extracted[m.LanguageTestKind](),
        candidate_name=name,
        date_of_birth=dob,
        test_date=test_date,
    )


# --- academic ----------------------------------------------------------------------------

_LEVELS = (
    (r"HIGHER\s*SECONDARY", m.AcademicLevel.HSC),
    (r"SECONDARY\s*SCHOOL\s*CERTIFICATE", m.AcademicLevel.SSC),
    (r"\bDAKHIL\b", m.AcademicLevel.DAKHIL),
    (r"\bALIM\b", m.AcademicLevel.ALIM),
    (r"\bDIPLOMA\b", m.AcademicLevel.DIPLOMA),
    (r"\bMASTER", m.AcademicLevel.MASTERS),
    (r"\bBACHELOR\b|\bB\.?\s?B\.?\s?A\b|\bB\.?\s?SC\b|\bB\.?\s?A\b(?=.*HONOU?RS)", m.AcademicLevel.BACHELOR),
    (r"\bH\.?\s?S\.?\s?C\b", m.AcademicLevel.HSC),
    (r"\bS\.?\s?S\.?\s?C\b", m.AcademicLevel.SSC),
)


_RANK = {
    m.AcademicLevel.SSC: 1, m.AcademicLevel.DAKHIL: 1,
    m.AcademicLevel.HSC: 2, m.AcademicLevel.ALIM: 2, m.AcademicLevel.DIPLOMA: 2,
    m.AcademicLevel.BACHELOR: 3, m.AcademicLevel.MASTERS: 4,
}


_CONFERS_DEGREE = re.compile(r"CONFERRED\s+(?:UPON\s+\w+\s+)?THE\s+DEGREE", re.IGNORECASE)


def _level(group: PageGroup) -> Extracted:
    """The highest level the page names: a bachelor transcript also says "HSC or equivalent"
    (its entry requirement), an HSC certificate never names a degree."""
    page = group.pages[0]
    hits = []
    for pattern, level in _LEVELS:
        line = next((ln for ln in page.lines if re.search(pattern, ln.text, re.IGNORECASE)), None)
        if line is not None:
            hits.append((level, line))
    if not hits:
        # A notary stamp over the degree line can leave only the layout reader's text,
        # merged into the stamp's block. A degree is trusted there when the line reader
        # confirms the page confers one ("HAS CONFERRED THE DEGREE OF").
        vl = [lv for pattern, lv in _LEVELS if re.search(pattern, page.block_text, re.IGNORECASE)]
        if vl:
            level = max(vl, key=_RANK.get)
            degree = level in (m.AcademicLevel.BACHELOR, m.AcademicLevel.MASTERS) and _CONFERS_DEGREE.search(page.line_text)
            return Extracted[m.AcademicLevel](value=level, confidence=SINGLE_READER_FACTOR if degree else 0.6, source_page=page.page_no)
        return Extracted[m.AcademicLevel](value=m.AcademicLevel.OTHER, confidence=0.5, source_page=page.page_no)
    level, line = max(hits, key=lambda h: _RANK[h[0]])
    return Extracted[m.AcademicLevel](value=level, confidence=round(min(line.score, AGREE_CAP), 4), source_page=page.page_no)


def _student_name(group: PageGroup) -> Extracted[str]:
    # OCR slips seen on stamped pages: "ame of Student" (N cut off), "Name of Srudent".
    labelled = _name(group, [r"N?ame\s*of\s*(?:the\s*)?(?:S\w?udent|Candidate)", r"Student'?s?\s*Name", r"Candidate'?s?\s*Name"])
    if labelled.value is not None:
        return labelled
    # Certificates: "This is to Certify that <name>" with the name on the same or next line.
    for page in group.pages:
        for ln in reading_order(page.lines):
            mt = re.search(r"certif[yg]\s+that\s*(.*)$", ln.text, re.IGNORECASE)  # 'certifg': y read as g
            if not mt:
                continue
            candidate = clean_value(mt.group(1))
            src = ln
            nxt = _following(page.lines, ln)
            if not candidate and nxt:
                candidate, src = clean_value(nxt[0].text), nxt[0]
            candidate = re.split(r"\s+(?:Son|Daughter|S/O|D/O)\b", candidate, flags=re.IGNORECASE)[0]
            if re.fullmatch(NAME, candidate or ""):
                return text_field(Found(candidate, src.score, page.page_no), page)
    return Extracted[str]()


def _following(lines, ln) -> list:
    """What reads on after `ln`: the rest of its row (left to right), then the next two rows.
    By position, not reading_order: one tall line (a stamp) can merge rows there."""
    h = max(1, ln.box[3] - ln.box[1])
    right = sorted((o for o in lines if o is not ln and same_row(ln, o) and o.box[0] > ln.box[0]), key=lambda o: o.box[0])
    below = [o for o in lines if o not in right and o is not ln and ln.box[3] - h * 0.25 < (o.box[1] + o.box[3]) / 2 <= ln.box[3] + 3 * h]
    return right + sorted(below, key=lambda o: (o.box[1], o.box[0]))


def _certificate_dob(group: PageGroup) -> Extracted[date]:
    labelled = _date(group, [r"Date\s*of\s*Birth", r"Birth\s*Date"])
    if labelled.value is not None:
        return labelled
    # Board certificates write it out: "...date of birth as recorded in his/her registration
    # card is Fifth August Two Thousand." (often wrapped onto the next line).
    for page in group.pages:
        for ln in reading_order(page.lines):
            if not re.search(r"date\s*of\s*birth", ln.text, re.IGNORECASE):
                continue
            # The sentence goes on right after it on its row, then wraps to lines starting at its
            # left margin; a stamp's words beside it don't. All of it: "Two Thousand" alone is
            # already a valid year (2000) when "Seven" is on the next line.
            h = max(1, ln.box[3] - ln.box[1])
            more = [o for o in _following(page.lines, ln) if (same_row(ln, o) and o.box[0] - ln.box[2] < 2 * h) or abs(o.box[0] - ln.box[0]) < 3 * h][:2]
            used = [ln, *more]
            d = parse_words_date(" ".join(x.text for x in used))
            if d is None:
                continue
            score = min(x.score for x in used)
            # The second reader must spell out the same date.
            vl = parse_words_date(page.block_text)
            if vl == d:
                conf = min(score, AGREE_CAP)
            elif vl is not None:
                conf = DISAGREE
            else:
                conf = score * SINGLE_READER_FACTOR
            return date_field(d, conf, page.page_no)
    return Extracted[date]()


def academic_certificate(group: PageGroup, doc_id: str) -> m.AcademicCertificate:
    return m.AcademicCertificate(
        doc_id=doc_id,
        pages=group.page_nos,
        level=_level(group),
        student_name=_student_name(group),
        date_of_birth=_certificate_dob(group),
        registration_number=_board_registration(group),
        notary=_notary(group),
    )


def academic_transcript(group: PageGroup, doc_id: str) -> m.AcademicTranscript:
    return m.AcademicTranscript(
        doc_id=doc_id,
        pages=group.page_nos,
        level=_level(group),
        student_name=_student_name(group),
        registration_number=_board_registration(group),
        notary=_notary(group),
    )


def e_apostille(group: PageGroup, doc_id: str) -> m.EApostille:
    qr = next((b for p in group.pages for b in p.barcodes if b.format.upper().startswith("QR")), None)
    return m.EApostille(doc_id=doc_id, pages=group.page_nos, qr_decoded=qr is not None, qr_url=qr.text if qr is not None else None)


def photo(group: PageGroup, doc_id: str) -> m.Photo:
    return m.Photo(doc_id=doc_id, pages=group.page_nos)


EXTRACTORS: dict[PageKind, Callable[[PageGroup, str], object]] = {
    PageKind.PASSPORT: passport,
    PageKind.PHOTO: photo,
    PageKind.BIRTH_CERTIFICATE: birth_certificate,
    PageKind.NID: nid,
    PageKind.DEATH_CERTIFICATE: death_certificate,
    PageKind.FRC: frc,
    PageKind.AFFIDAVIT: affidavit,
    PageKind.BANK_SOLVENCY: bank_solvency,
    PageKind.BANK_STATEMENT: bank_statement,
    PageKind.TRADE_LICENSE: trade_license,
    PageKind.EMPLOYMENT_CERTIFICATE: employment_certificate,
    PageKind.TIN_CERTIFICATE: tin_certificate,
    PageKind.TAX_CHALLAN: tax_challan,
    PageKind.TAX_ACKNOWLEDGEMENT: tax_acknowledgement,
    PageKind.TAX_CERTIFICATE: tax_certificate,
    PageKind.E_APOSTILLE: e_apostille,
    PageKind.ACADEMIC_CERTIFICATE: academic_certificate,
    PageKind.ACADEMIC_TRANSCRIPT: academic_transcript,
    PageKind.LANGUAGE_TEST: language_test,
}

"""Text helpers for extraction: normalising, reading order, label/value lookup, fuzzy search."""

from __future__ import annotations

import html
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from hklv_ocr.reading import PageReading, TextLine

ROW_FIRST_GAP_PX = 700  # label -> its value in a two-column form (300 dpi)
ROW_NEXT_GAP_PX = 150  # between pieces of one value (digit boxes, words)

_BANGLA = re.compile(r"[ঀ-৿]")
_LATIN = re.compile(r"[A-Za-z]")


def squash(s: str) -> str:
    """Uppercase letters and digits only: 'Abdul  Karim.' and 'ABDULKARIM' compare equal."""
    return re.sub(r"[^A-Z0-9ঀ-৿]", "", s.upper())


def clean_value(s: str) -> str:
    """Trim separators and stray punctuation OCR leaves around a field value."""
    s = re.sub(r"\s+", " ", s).strip()
    return s.strip(" :;,.-_|*#\"'").strip()


def bangla_ratio(text: str) -> float:
    b, latin = len(_BANGLA.findall(text)), len(_LATIN.findall(text))
    return b / (b + latin) if b + latin else 0.0


def reading_order(lines: Iterable[TextLine]) -> list[TextLine]:
    """Top-to-bottom rows, left-to-right within a row (rows: overlapping vertical centres)."""
    ordered = sorted(lines, key=lambda ln: (ln.box[1], ln.box[0]))
    rows: list[list[TextLine]] = []
    for ln in ordered:
        mid = (ln.box[1] + ln.box[3]) / 2
        if rows:
            last = rows[-1][0]
            height = max(1, last.box[3] - last.box[1])
            if abs(mid - (last.box[1] + last.box[3]) / 2) < height * 0.5:
                rows[-1].append(ln)
                continue
        rows.append([ln])
    return [ln for row in rows for ln in sorted(row, key=lambda x: x.box[0])]


def same_row(a: TextLine, b: TextLine) -> bool:
    height = max(1, a.box[3] - a.box[1])
    return abs((a.box[1] + a.box[3]) / 2 - (b.box[1] + b.box[3]) / 2) < height * 0.5


def as_lines_page(page: PageReading, score: float) -> PageReading:
    """PaddleOCR-VL's block text as a page of lines (table cells become lines), all at `score`."""
    lines = []
    y = 0
    for block in page.blocks:
        for raw in re.sub(r"<[^>]+>", "\n", block.text).splitlines():
            text = html.unescape(raw).strip()
            if text:
                lines.append(TextLine(text=text, score=score, box=(0, y, 1000, y + 20)))
                y += 40
    return page.model_copy(update={"lines": tuple(lines)})


@dataclass(frozen=True)
class Found:
    """A value found on a page, with the score of the line(s) it came from."""

    value: str
    score: float
    page_no: int


def find_labeled(
    page: PageReading,
    labels: Sequence[str],
    *,
    value_pattern: str = r".+",
    stop_words: Sequence[str] = (),
) -> Found | None:
    """Find 'Label: value' on one line, or 'Label' with the value on the next line.

    `labels` are regexes matched case-insensitively at a word boundary. The value is cut at
    any of `stop_words` (the next label printed on the same line).
    """
    lines = reading_order(page.lines)
    label_re = re.compile(r"(?:^|\b)(?:" + "|".join(labels) + r")\s*[:：\-]?\s*", re.IGNORECASE)
    value_re = re.compile(r"^(" + value_pattern + r")", re.IGNORECASE)
    stop_re = re.compile(r"\s+(?:" + "|".join(stop_words) + r")\b.*$", re.IGNORECASE) if stop_words else None

    def take(text: str) -> str | None:
        if stop_re:
            text = stop_re.sub("", text)
        m = value_re.match(clean_value(text))
        return clean_value(m.group(1)) if m and clean_value(m.group(1)) else None

    for i, ln in enumerate(lines):
        m = label_re.search(ln.text)
        if not m:
            continue
        rest = ln.text[m.end() :]
        v = take(rest)
        if v:
            return Found(v, ln.score, page.page_no)
        # Value to the right on the same row: a two-column form, or one digit per box. Only
        # neighbours close to the label, then to each other; a far column is another field.
        candidates = sorted((o for o in lines if o is not ln and o.box[0] >= ln.box[2] - 10 and same_row(ln, o)), key=lambda o: o.box[0])
        row: list[TextLine] = []
        edge = ln.box[2]
        for o in candidates:
            if o.box[0] - edge > (ROW_FIRST_GAP_PX if not row else ROW_NEXT_GAP_PX):
                break
            row.append(o)
            edge = o.box[2]
        if row:
            texts = [o.text.strip() for o in row]
            boxed = all(len(t) <= 2 and t.isdigit() for t in texts)
            v = take("".join(texts) if boxed else " ".join(texts))
            if v:
                return Found(v, min(o.score for o in [ln, *row]), page.page_no)
        # Value on the next line (same column or right of the label).
        for nxt in lines[i + 1 : i + 3]:
            if label_re.search(nxt.text):
                break
            v = take(nxt.text)
            if v:
                return Found(v, min(ln.score, nxt.score), page.page_no)
    return None


def levenshtein(a: str, b: str, limit: int | None = None) -> int:
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if limit is not None and min(cur) > limit:
            return limit + 1
        prev = cur
    return prev[-1]


def closest_window(needle: str, haystack: str) -> tuple[int, str]:
    """Smallest edit distance between `needle` and any same-length-ish window of `haystack`."""
    if not needle:
        return (0, "")
    if needle in haystack:
        return (0, needle)
    best = (len(needle) + 1, "")
    n = len(needle)
    for size in (n - 1, n, n + 1):
        if size <= 0:
            continue
        for start in range(0, max(1, len(haystack) - size + 1)):
            window = haystack[start : start + size]
            d = levenshtein(needle, window, limit=best[0])
            if d < best[0]:
                best = (d, window)
                if d == 1:
                    return best
    return best

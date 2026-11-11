"""Findings shared by many document types: notarisation, stamps, language, translation."""

from __future__ import annotations

import re
from collections.abc import Sequence

from hklv_ocr.reading import Box, LayoutBlock, PageReading
from hklv_rules.models.common import Extracted, Language, NotaryInfo

from .confidence import AGREE_CAP, SINGLE_READER_FACTOR
from .text import bangla_ratio

NOTARY_RE = re.compile(r"\bNOTARY\s*PUBLIC\b|\bADVOCATE\b", re.IGNORECASE)
TRANSLATION_RE = re.compile(r"\bTRANSLAT(?:ED|ION)\b|\bTRUE\s+TRANSLATION\b|\bENGLISH\s+VERSION\b", re.IGNORECASE)

# Seal detection has no calibrated score yet. A detected seal block with no layout score,
# or no detected seal at all, stays below the default 0.90 threshold: FLAG, not a guess.
SEAL_UNSCORED = 0.85
NO_SEAL_SEEN = 0.50
SEAL_MIN_SCORE = 0.50  # weaker detections are not corroborated, whatever is nearby
SEAL_NEAR_PX = 400  # ~3.4 cm at 300 dpi
SEAL_WITH_NOTARY_TEXT = 0.95
NO_NOTARY_TEXT = 0.80  # both readers read the whole page and neither found the words


def notary_info(pages: Sequence[PageReading]) -> NotaryInfo:
    if not pages:
        return NotaryInfo()
    text_hits = [ln for p in pages for ln in p.lines if NOTARY_RE.search(ln.text)]
    vl_hit = any(NOTARY_RE.search(p.block_text) for p in pages)
    if text_hits:
        best = max(ln.score for ln in text_hits)
        conf = min(best, AGREE_CAP) if vl_hit else best * SINGLE_READER_FACTOR
        notary_text = Extracted[bool](value=True, confidence=round(conf, 4), source_page=_page_of(pages, text_hits[0]))
    elif vl_hit:
        notary_text = Extracted[bool](value=True, confidence=0.6, source_page=_first_page(pages, lambda p: NOTARY_RE.search(p.block_text)))
    else:
        notary_text = Extracted[bool](value=False, confidence=NO_NOTARY_TEXT, source_page=pages[0].page_no)

    seals = [(p, b, _seal_confidence(p, b)) for p in pages for b in p.blocks if b.label == "seal"]
    if seals:
        page, _, conf = max(seals, key=lambda s: s[2])
        stamp = Extracted[bool](value=True, confidence=round(conf, 4), source_page=page.page_no)
    else:
        stamp = Extracted[bool](value=False, confidence=NO_SEAL_SEEN, source_page=pages[0].page_no)
    return NotaryInfo(notary_text_present=notary_text, stamp_present=stamp)


def _gap(a: Box, b: Box) -> int:
    """Pixels between two boxes (0 if they overlap)."""
    dx = max(0, max(a[0], b[0]) - min(a[2], b[2]))
    dy = max(0, max(a[1], b[1]) - min(a[3], b[3]))
    return max(dx, dy)


def _seal_confidence(page: PageReading, seal: LayoutBlock) -> float:
    """A seal next to "Notary Public"/"Advocate" text is that attestation's stamp.

    The layout detector scores seals 0.5-0.95 even when they are plainly there (stamps
    overprint text). Two independent signals in the same spot, a seal-shaped mark and
    the notary's own wording, confirm each other; a seal elsewhere keeps its own score.
    """
    own = seal.score if seal.score is not None else SEAL_UNSCORED
    if own < SEAL_MIN_SCORE:
        return own
    near_text = [ln for ln in page.lines if NOTARY_RE.search(ln.text) and _gap(ln.box, seal.box) <= SEAL_NEAR_PX]
    if near_text:
        return max(own, min(max(ln.score for ln in near_text), SEAL_WITH_NOTARY_TEXT))
    return own


def page_language(page: PageReading) -> Language:
    # PP-OCRv6 has no Bangla model; VL turns Bangla into other scripts. Use both signals:
    # Bangla characters in VL output, or many low-confidence lines in PP output.
    ratio = bangla_ratio(page.block_text)
    if ratio > 0.6:
        return Language.BANGLA
    if ratio > 0.15:
        return Language.MIXED
    return Language.ENGLISH


def document_language(pages: Sequence[PageReading]) -> Extracted[Language]:
    if not pages:
        return Extracted[Language]()
    langs = {page_language(p) for p in pages}
    if Language.BANGLA in langs or Language.MIXED in langs:
        value = Language.BANGLA if langs == {Language.BANGLA} else Language.MIXED
    else:
        value = Language.ENGLISH
    # Language is a whole-page judgement over hundreds of characters, not a single field.
    return Extracted[Language](value=value, confidence=0.95, source_page=pages[0].page_no)


def has_translation(pages: Sequence[PageReading]) -> Extracted[bool]:
    """An English page sits next to the Bangla original, or a page says it is a translation."""
    if not pages:
        return Extracted[bool]()
    english = [p for p in pages if page_language(p) == Language.ENGLISH and len(p.lines) >= 8]
    marked = [p for p in english if TRANSLATION_RE.search(p.line_text) or TRANSLATION_RE.search(p.block_text)]
    if marked:
        return Extracted[bool](value=True, confidence=0.95, source_page=marked[0].page_no)
    if english and len(english) < len(pages):
        return Extracted[bool](value=True, confidence=0.9, source_page=english[0].page_no)
    if english:
        return Extracted[bool](value=False, confidence=0.6, source_page=english[0].page_no)
    return Extracted[bool](value=False, confidence=0.9, source_page=pages[0].page_no)


def _page_of(pages: Sequence[PageReading], line) -> int:
    for p in pages:
        if line in p.lines:
            return p.page_no
    return pages[0].page_no


def _first_page(pages: Sequence[PageReading], pred) -> int:
    for p in pages:
        if pred(p):
            return p.page_no
    return pages[0].page_no

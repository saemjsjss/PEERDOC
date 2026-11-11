"""Turn reader agreement into the confidence score the rules engine thresholds on.

PaddleOCR-VL gives no scores, and a single reader can be confidently wrong (one-letter
name errors). So a value read by PP-OCRv6 is checked against PaddleOCR-VL's text of the
same page:

* both readers contain it              -> the line score, capped at AGREE_CAP
* the other reader has a near-miss      -> DISAGREE (below threshold: FLAG, never a guess)
* the other reader has nothing like it  -> line score x SINGLE_READER_FACTOR
* MRZ field with valid check digits     -> MRZ_VALID

These numbers are placeholders until calibrated on more real cases; with the default
threshold of 0.90 a single reader needs a line score of at least ~0.98 to pass alone.
"""

from __future__ import annotations

from datetime import date
from typing import TypeVar

from hklv_ocr.reading import PageReading
from hklv_rules.models.common import Extracted

from .text import Found, closest_window, squash

AGREE_CAP = 0.99
SINGLE_READER_FACTOR = 0.92
DISAGREE = 0.50
MRZ_VALID = 0.99
MRZ_INVALID = 0.40
VL_ONLY = 0.60  # only PaddleOCR-VL (no score) saw the value

T = TypeVar("T")


def agreement(value: str, page: PageReading) -> str:
    """'agree', 'disagree' or 'absent': how PaddleOCR-VL's text of the page relates to `value`."""
    needle, hay = squash(value), squash(page.block_text)
    if not needle or not hay:
        return "absent"
    dist, _ = closest_window(needle, hay)
    if dist == 0:
        return "agree"
    # A near-miss means the second reader saw this field but read it differently.
    if dist <= max(1, len(needle) // 5):
        return "disagree"
    return "absent"


def score_text(found: Found, page: PageReading) -> float:
    verdict = agreement(found.value, page)
    if verdict == "agree":
        return min(found.score, AGREE_CAP)
    if verdict == "disagree":
        return DISAGREE
    return found.score * SINGLE_READER_FACTOR


def text_field(found: Found | None, page: PageReading | None) -> Extracted[str]:
    if found is None or page is None:
        return Extracted[str]()
    return Extracted[str](value=found.value, confidence=round(score_text(found, page), 4), source_page=found.page_no)


def derived(value: T | None, confidence: float, page_no: int | None) -> Extracted:
    """A value computed from other evidence (a parsed date, a yes/no finding)."""
    if value is None:
        return Extracted()
    return Extracted(value=value, confidence=round(max(0.0, min(1.0, confidence)), 4), source_page=page_no)


def date_field(value: date | None, confidence: float, page_no: int | None) -> Extracted[date]:
    if value is None:
        return Extracted[date]()
    return Extracted[date](value=value, confidence=round(confidence, 4), source_page=page_no)

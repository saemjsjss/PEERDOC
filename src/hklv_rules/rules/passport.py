"""Rulebook v2.5 section 4.1: Passport (PASSPORT-01).

PASSPORT-01 (Expiry), one result per Passport:
  * Expiry before the evaluation date -> FAIL ("expired on ...").
  * Expiry less than 12 months after the evaluation date -> FAIL. Exactly 12 months is OK.
  * Expiry missing or read with low confidence -> FLAG.
  * "If MRZ and Print mismatch -> FLAG": the printed name (given names + surname) must equal
    the MRZ name (MRZ given names + MRZ surname) after name cleanup. Word order is ignored
    ('UDDIN KAMAL' == 'KAMAL UDDIN'). Different -> FLAG; missing or unreliable -> FLAG.
  * "If MRZ and Print mismatch -> FLAG" also applies to the expiry itself: the printed
    'Date of Expiry' and the MRZ expiry, both reliable and different -> FLAG. A printed
    expiry that is missing or unreliable adds no finding while the MRZ expiry is reliable
    (the MRZ date is check-digit-verified); the reason says "printed expiry not read".
The outcome is the worst of the expiry, expiry-agreement and name checks; the reason reports all.
No passport at all -> one FAIL (REQ-01 also fails).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date

from ..context import EvaluationContext
from ..models import Extracted, Outcome, Passport, RuleResult, worst
from ..names import normalize_name
from ._evidence import ev
from ._shared import add_months

PASSPORT_01 = "PASSPORT-01"
ALL_RULES = (PASSPORT_01,)
MIN_VALIDITY_MONTHS = 12


def check_passport(ctx: EvaluationContext) -> list[RuleResult]:
    passports = ctx.case.of_kind(Passport)
    if not passports:
        return [RuleResult(rule_id=PASSPORT_01, outcome=Outcome.FAIL, reason="No passport found")]
    return [_passport_01(p, ctx) for p in passports]


def _passport_01(p: Passport, ctx: EvaluationContext) -> RuleResult:
    expiry_outcome, expiry_reason = _expiry(p.date_of_expiry, ctx)
    agree_outcome, agree_reason = _expiry_agreement(p, ctx)
    name_outcome, name_reason = _names(p, ctx)
    evidence = (
        ev(p.doc_id, "date_of_expiry", p.date_of_expiry),
        ev(p.doc_id, "printed_date_of_expiry", p.printed_date_of_expiry),
        ev(p.doc_id, "given_names", p.given_names),
        ev(p.doc_id, "surname", p.surname),
        ev(p.doc_id, "mrz_given_names", p.mrz_given_names),
        ev(p.doc_id, "mrz_surname", p.mrz_surname),
    )
    return RuleResult(
        rule_id=PASSPORT_01,
        outcome=worst((expiry_outcome, agree_outcome, name_outcome)),
        reason=f"Passport {p.doc_id}: {expiry_reason}; {agree_reason}; {name_reason}",
        evidence=evidence,
    )


# --- Expiry -----------------------------------------------------------------------


def _expiry(expiry: Extracted[date], ctx: EvaluationContext) -> tuple[Outcome, str]:
    if not expiry.found:
        return Outcome.FLAG, "date of expiry not found"
    if not expiry.is_reliable(ctx.threshold):
        return Outcome.FLAG, f"date of expiry {expiry.value:%d-%m-%Y} read with low OCR confidence"
    today = ctx.case.evaluation_date
    cutoff = add_months(today, MIN_VALIDITY_MONTHS)
    if expiry.value < today:
        return Outcome.FAIL, f"expired on {expiry.value:%d-%m-%Y} (evaluation date {today:%d-%m-%Y})"
    if expiry.value < cutoff:
        return (
            Outcome.FAIL,
            f"expires on {expiry.value:%d-%m-%Y}, less than {MIN_VALIDITY_MONTHS} months after "
            f"{today:%d-%m-%Y} (needs {cutoff:%d-%m-%Y} or later)",
        )
    return (
        Outcome.PASS,
        f"valid until {expiry.value:%d-%m-%Y}, at least {MIN_VALIDITY_MONTHS} months after {today:%d-%m-%Y}",
    )


# --- Printed expiry vs MRZ expiry -------------------------------------------------


def _has_mrz(p: Passport) -> bool:
    return p.mrz_surname.found or p.mrz_given_names.found


def _expiry_agreement(p: Passport, ctx: EvaluationContext) -> tuple[Outcome, str]:
    """Rulebook 4.1 "If MRZ and Print mismatch -> FLAG", applied to the expiry date.

    Only a mismatch between two reliable dates is a finding here. Any other problem with
    the MRZ expiry (missing, low confidence) is already a FLAG from `_expiry`.
    """
    mrz, printed = p.date_of_expiry, p.printed_date_of_expiry
    if not _has_mrz(p):
        # No MRZ read: date_of_expiry itself comes from the print; nothing to compare.
        return Outcome.PASS, "no MRZ read, expiry taken from the printed page"
    if not mrz.found or not mrz.is_reliable(ctx.threshold):
        return Outcome.PASS, "printed expiry not compared (MRZ expiry missing or unreliable)"
    if not printed.found:
        return Outcome.PASS, "printed expiry not read (MRZ expiry is check-digit-verified)"
    if not printed.is_reliable(ctx.threshold):
        return (
            Outcome.PASS,
            f"printed expiry not read reliably ({printed.value:%d-%m-%Y}, low OCR confidence; "
            "MRZ expiry is check-digit-verified)",
        )
    if printed.value != mrz.value:
        return (
            Outcome.FLAG,
            f"printed expiry {printed.value:%d-%m-%Y} does not match MRZ expiry {mrz.value:%d-%m-%Y}",
        )
    return Outcome.PASS, f"printed expiry matches MRZ expiry {mrz.value:%d-%m-%Y}"


# --- Printed name vs MRZ name -----------------------------------------------------


def _names(p: Passport, ctx: EvaluationContext) -> tuple[Outcome, str]:
    printed = _joined("printed name", (p.given_names, p.surname), ctx)
    mrz = _joined("MRZ name", (p.mrz_given_names, p.mrz_surname), ctx)
    problems = [problem for _, problem in (printed, mrz) if problem]
    if problems:
        return Outcome.FLAG, f"{' and '.join(problems)}, so printed and MRZ names can't be confirmed to match"
    printed_name, mrz_name = printed[0], mrz[0]
    if _same_name(printed_name, mrz_name):
        return Outcome.PASS, f"printed name '{printed_name}' matches MRZ name '{mrz_name}'"
    return Outcome.FLAG, f"printed name '{printed_name}' does not match MRZ name '{mrz_name}'"


def _joined(label: str, parts: tuple[Extracted[str], ...], ctx: EvaluationContext) -> tuple[str, str | None]:
    """(given names + surname joined, problem or None). A part absent from the page is
    skipped (single-name passports); both absent, or any part unreliable, is a problem."""
    found = [x for x in parts if x.found and x.value.strip()]
    if not found:
        return "", f"{label} not found"
    if any(not x.is_reliable(ctx.threshold) for x in found):
        return "", f"{label} read with low OCR confidence"
    return " ".join(x.value.strip() for x in found), None


def _words(raw: str) -> list[str]:
    # MRZ fillers ('<') and punctuation separate words just like spaces.
    text = unicodedata.normalize("NFKC", raw).upper()
    return sorted(w for w in (normalize_name(t) for t in re.findall(r"[^\W\d_]+", text)) if w)


def _same_name(a: str, b: str) -> bool:
    key_a, key_b = normalize_name(a), normalize_name(b)
    if key_a and key_a == key_b:
        return True
    words_a = _words(a)
    return bool(words_a) and words_a == _words(b)

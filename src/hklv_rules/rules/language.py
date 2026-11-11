"""Rulebook v2.5 section 4.10: IELTS / TOPIK (LANG-01, LANG-02). Optional document.

No language test submitted -> no results (absence is fine; REQ-10's optional-document
reporting covers it). Each submitted test gets one LANG-01 and one LANG-02 result.
"""

from __future__ import annotations

from datetime import date

from ..context import EvaluationContext
from ..identity import MatchKind, compare_name
from ..models import Evidence, LanguageTest, Outcome, Passport, Person, RuleResult, worst
from ._evidence import ev
from ._shared import subtract_months

LANG_01, LANG_02 = "LANG-01", "LANG-02"
ALL_RULES = (LANG_01, LANG_02)
VALIDITY_MONTHS = 24  # "within 2 years"

_NAME_OUTCOME = {
    MatchKind.EXACT: Outcome.PASS,
    MatchKind.AFFIDAVIT: Outcome.PASS,
    MatchKind.UNCERTAIN: Outcome.FLAG,
    MatchKind.MISMATCH: Outcome.FAIL,
}


def check_language_tests(ctx: EvaluationContext) -> list[RuleResult]:
    results: list[RuleResult] = []
    for test in ctx.case.of_kind(LanguageTest):
        results += [_lang_01_expiry(test, ctx), _lang_02_identity(test, ctx)]
    return results


def _label(test: LanguageTest, ctx: EvaluationContext) -> str:
    kind = test.test.value.value if test.test.is_reliable(ctx.threshold) else "IELTS/TOPIK"
    return f"{kind} {test.doc_id}"


# --- LANG-01 Expiry ---------------------------------------------------------------------


def _lang_01_expiry(test: LanguageTest, ctx: EvaluationContext) -> RuleResult:
    where = _label(test, ctx)
    taken = test.test_date
    evidence = (ev(test.doc_id, "test_date", taken),)

    def result(outcome: Outcome, reason: str) -> RuleResult:
        return RuleResult(rule_id=LANG_01, outcome=outcome, reason=reason, evidence=evidence)

    if not taken.found:
        return result(Outcome.FLAG, f"{where}: test date not found, so expiry can't be checked")
    if not taken.is_reliable(ctx.threshold):
        return result(
            Outcome.FLAG,
            f"{where}: test date {taken.value:%d-%m-%Y} read with low OCR confidence ({taken.confidence:.2f})",
        )
    today = ctx.case.evaluation_date
    cutoff = subtract_months(today, VALIDITY_MONTHS)
    if taken.value > today:
        return result(
            Outcome.FLAG,
            f"{where}: test date {taken.value:%d-%m-%Y} is after the evaluation date {today:%d-%m-%Y} (likely misread)",
        )
    if taken.value >= cutoff:
        return result(
            Outcome.PASS,
            f"{where}: taken {taken.value:%d-%m-%Y}, within 2 years (on or after {cutoff:%d-%m-%Y})",
        )
    return result(
        Outcome.FAIL,
        f"{where}: taken {taken.value:%d-%m-%Y}, expired (older than 2 years; cutoff {cutoff:%d-%m-%Y})",
    )


# --- LANG-02 Name / DOB -------------------------------------------------------------------


def _lang_02_identity(test: LanguageTest, ctx: EvaluationContext) -> RuleResult:
    where = _label(test, ctx)
    evidence: list[Evidence] = [
        ev(test.doc_id, "candidate_name", test.candidate_name),
        ev(test.doc_id, "date_of_birth", test.date_of_birth),
    ]

    student = ctx.anchors.student
    if student.name is None:
        # No StudentRef to compare against: missing reference data is a FLAG, not a FAIL.
        name_outcome, name_reason = Outcome.FLAG, f"name can't be checked: {student.describe()}"
    else:
        cmp = compare_name(test.candidate_name, Person.STUDENT, ctx)
        name_outcome = _NAME_OUTCOME[cmp.kind]
        name_reason = f"name: {cmp.reason}"

    dob_outcome, dob_reason, passport_evidence = _dob_check(test, ctx)
    evidence += passport_evidence

    return RuleResult(
        rule_id=LANG_02,
        outcome=worst([name_outcome, dob_outcome]),
        reason=f"{where}: {name_reason}; {dob_reason}",
        evidence=tuple(evidence),
    )


def _dob_check(test: LanguageTest, ctx: EvaluationContext) -> tuple[Outcome, str, list[Evidence]]:
    """Language test DOB vs the passport DOB (StudentRef's date of birth)."""
    passports = ctx.case.of_kind(Passport)
    passport_evidence = [ev(p.doc_id, "date_of_birth", p.date_of_birth) for p in passports]
    dob = test.date_of_birth

    if not dob.found:
        return Outcome.FLAG, "date of birth not found on the test", passport_evidence
    if not dob.is_reliable(ctx.threshold):
        return (
            Outcome.FLAG,
            f"date of birth {dob.value:%d-%m-%Y} read with low OCR confidence ({dob.confidence:.2f})",
            passport_evidence,
        )

    reference, problem = _passport_dob(passports, ctx)
    if reference is None:
        return Outcome.FLAG, f"date of birth {dob.value:%d-%m-%Y} can't be checked: {problem}", passport_evidence
    if dob.value == reference:
        return Outcome.PASS, f"date of birth {dob.value:%d-%m-%Y} matches the passport", passport_evidence
    return (
        Outcome.FAIL,
        f"date of birth {dob.value:%d-%m-%Y} does not match the passport date of birth {reference:%d-%m-%Y}",
        passport_evidence,
    )


def _passport_dob(passports: list[Passport], ctx: EvaluationContext) -> tuple[date | None, str]:
    if not passports:
        return None, "no passport"
    reliable = {p.date_of_birth.value for p in passports if p.date_of_birth.is_reliable(ctx.threshold)}
    if not reliable:
        if not any(p.date_of_birth.found for p in passports):
            return None, "passport date of birth not found"
        return None, "passport date of birth read with low OCR confidence"
    if len(reliable) > 1:
        dates = ", ".join(f"{d:%d-%m-%Y}" for d in sorted(reliable))
        return None, f"passports disagree on the date of birth ({dates})"
    return next(iter(reliable)), ""

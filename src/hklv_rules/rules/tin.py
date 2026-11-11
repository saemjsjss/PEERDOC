"""Rulebook v2.5 section 4.7: TIN Certificate (TIN-01 .. TIN-03).

One result per rule per TIN Certificate. No TIN -> no results (REQ-07 reports it).

TIN-03 compares the taxpayer name with the Trade License owner. When no Trade License
was submitted, the Employment Certificate employee takes its place (REQ-06 and the
supplement's 5.1 note). Which parent the name belongs to is CHAIN-02's job, not this one.
"""

from __future__ import annotations

from enum import Enum

from ..context import EvaluationContext
from ..identity import MatchKind, affidavit_bridge
from ..models import EmploymentCertificate, Extracted, Outcome, RuleResult, TinCertificate, TradeLicense
from ..names import normalize_name
from ._evidence import ev
from ._shared import number_match_rule
from .financial_chain import _PARENTS, _Income

TIN_01, TIN_02, TIN_03 = "TIN-01", "TIN-02", "TIN-03"
ALL_RULES = (TIN_01, TIN_02, TIN_03)


def check_tin(ctx: EvaluationContext) -> list[RuleResult]:
    results: list[RuleResult] = []
    for tin in ctx.case.of_kind(TinCertificate):
        results += [_tin_01_qr(tin), _tin_02_number(tin, ctx), _tin_03_name(tin, ctx)]
    return results


def _label(tin: TinCertificate) -> str:
    return f"TIN Certificate {tin.doc_id}"


# --- TIN-01 QR ------------------------------------------------------------------


def _qr_evidence(tin: TinCertificate) -> tuple:
    # ZXing decoding is exact: it either decodes (confidence 1.0) or it doesn't.
    return (ev(tin.doc_id, "qr_decoded", Extracted[bool](value=tin.qr_decoded, confidence=1.0)),)


def _tin_01_qr(tin: TinCertificate) -> RuleResult:
    if tin.qr_decoded:
        outcome, reason = Outcome.PASS, f"{_label(tin)}: QR code decoded"
    else:
        outcome, reason = Outcome.FLAG, f"{_label(tin)}: QR could not be decoded"
    return RuleResult(rule_id=TIN_01, outcome=outcome, reason=reason, evidence=_qr_evidence(tin))


# --- TIN-02 Number match ----------------------------------------------------------


def _tin_02_number(tin: TinCertificate, ctx: EvaluationContext) -> RuleResult:
    if not tin.qr_decoded:
        return RuleResult(
            rule_id=TIN_02,
            outcome=Outcome.FLAG,
            reason=f"{_label(tin)}: QR could not be decoded, so the printed TIN can't be checked against it",
            evidence=(ev(tin.doc_id, "tin_printed", tin.tin_printed), *_qr_evidence(tin)),
        )
    if tin.tin_from_qr is None:
        return RuleResult(
            rule_id=TIN_02,
            outcome=Outcome.FLAG,
            reason=f"{_label(tin)}: QR decoded but contains no TIN, so the printed TIN can't be checked against it",
            evidence=(ev(tin.doc_id, "tin_printed", tin.tin_printed), *_qr_evidence(tin)),
        )
    from_qr = Extracted[str](value=tin.tin_from_qr, confidence=1.0, source_page=tin.tin_printed.source_page)
    return number_match_rule(
        TIN_02, tin.doc_id, _label(tin), ("tin_printed", tin.tin_printed), ("tin_from_qr", from_qr), ctx
    )


# --- TIN-03 Name match --------------------------------------------------------------


class _Verdict(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    UNSURE = "UNSURE"


def _readable(name: Extracted[str], ctx: EvaluationContext) -> bool:
    return name.is_reliable(ctx.threshold) and bool(normalize_name(name.value))


def _unreadable_why(label: str, name: Extracted[str]) -> str:
    if name.found and normalize_name(name.value):
        return f"{label} '{name.value}' read with low OCR confidence"
    return f"{label} not found by OCR"


def _compare(tin_name: str, income: _Income, ctx: EvaluationContext) -> tuple[_Verdict, str]:
    """Identical after normalisation, or a spelling difference covered by a valid
    same-person affidavit for either parent (5.2)."""
    who = f"{income.describe} '{income.name.value}' ({income.doc_id})"
    if not _readable(income.name, ctx):
        return _Verdict.UNSURE, _unreadable_why(f"{income.describe} name ({income.doc_id})", income.name)
    if normalize_name(tin_name) == normalize_name(income.name.value):
        return _Verdict.MATCH, f"matches {who}"
    verdicts = [affidavit_bridge(ctx, p, tin_name, income.name.value) for p in _PARENTS]
    for kind, why in verdicts:
        if kind is MatchKind.AFFIDAVIT:
            return _Verdict.MATCH, f"matches {who}; spelling difference covered by {why}"
    unsure = [why for kind, why in verdicts if kind is MatchKind.UNCERTAIN]
    if unsure:
        return _Verdict.UNSURE, f"differs from {who}; {'; '.join(unsure)}"
    return _Verdict.MISMATCH, f"does not match {who}"


def _tin_03_name(tin: TinCertificate, ctx: EvaluationContext) -> RuleResult:
    trades = ctx.case.of_kind(TradeLicense)
    employments = ctx.case.of_kind(EmploymentCertificate)
    incomes = [_Income.of(d) for d in (trades or employments)]
    substitution = (
        " (no Trade License submitted; compared with the Employment Certificate instead)"
        if employments and not trades
        else ""
    )
    evidence = (
        ev(tin.doc_id, "taxpayer_name", tin.taxpayer_name),
        *(ev(i.doc_id, i.field, i.name) for i in incomes),
    )

    def result(outcome: Outcome, reason: str) -> RuleResult:
        return RuleResult(
            rule_id=TIN_03, outcome=outcome, reason=f"{_label(tin)}: {reason}{substitution}", evidence=evidence
        )

    if not incomes:
        return result(Outcome.FLAG, "No Trade License to compare with")
    if not _readable(tin.taxpayer_name, ctx):
        return result(Outcome.FLAG, _unreadable_why("taxpayer name", tin.taxpayer_name))

    name = tin.taxpayer_name.value
    compared = [_compare(name, i, ctx) for i in incomes]
    verdicts = {v for v, _ in compared}
    details = "; ".join(why for _, why in compared)
    if verdicts == {_Verdict.MATCH}:
        return result(Outcome.PASS, f"taxpayer '{name}' {details}")
    if verdicts == {_Verdict.MISMATCH}:
        return result(Outcome.FAIL, f"taxpayer '{name}' {details}")
    return result(Outcome.FLAG, f"taxpayer '{name}' could not be confirmed against every document: {details}")

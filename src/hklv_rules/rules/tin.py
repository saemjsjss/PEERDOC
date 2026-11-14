"""Rulebook v2.5 section 4.7: TIN Certificate (TIN-01 .. TIN-03).

One result per rule per TIN Certificate. No TIN -> no results (REQ-07 reports it).

TIN-03 (RULES-v9): the taxpayer must be the father or mother. Whether the TIN and the
income document belong to the same parent is CHAIN-02's job.
"""

from __future__ import annotations

from ..context import EvaluationContext
from ..models import Extracted, Outcome, Person, RuleResult, TinCertificate
from ._evidence import ev
from ._shared import assign_by_name, number_match_rule

TIN_01, TIN_02, TIN_03 = "TIN-01", "TIN-02", "TIN-03"
ALL_RULES = (TIN_01, TIN_02, TIN_03)


def check_tin(ctx: EvaluationContext) -> list[RuleResult]:
    results: list[RuleResult] = []
    for tin in ctx.case.of_kind(TinCertificate):
        results += [_tin_01_qr(tin), _tin_02_number(tin, ctx), _tin_03_taxpayer(tin, ctx)]
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


# --- TIN-03 Taxpayer --------------------------------------------------------------


def _tin_03_taxpayer(tin: TinCertificate, ctx: EvaluationContext) -> RuleResult:
    """RULES-v9: the taxpayer is assigned by name to the father or mother (Section 0).

    Replaces v8's TIN-03 (taxpayer == income-document holder) and CHAIN-03 (TIN not the
    student's): whether the TIN and the income document belong to the same parent is CHAIN-02."""
    assignment = assign_by_name(
        TIN_03,
        "TIN Certificate",
        [(tin.doc_id, "taxpayer_name", tin.taxpayer_name)],
        ctx,
        allowed=(Person.FATHER, Person.MOTHER),
        unknown_reason="is not in the father's or mother's name",
    )
    return assignment.results[0]

"""Rulebook v2.5 section 5.1: the financial chain (strict parent match).

TIN Taxpayer and Trade License Owner must be the same parent. Bank documents are
deliberately NOT part of this chain.

Not yet covered: the Employment Certificate alternative to the Trade License
(REQ-06), which has no signature or extraction model until its rules are approved.
"""

from __future__ import annotations

from ..context import EvaluationContext
from ..identity import Identification, IdStatus, affidavit_bridge, identify, MatchKind
from ..models import Outcome, Person, RuleResult, TinCertificate, TradeLicense
from ..names import normalize_name
from ._evidence import ev

CHAIN_01, CHAIN_02, CHAIN_03 = "CHAIN-01", "CHAIN-02", "CHAIN-03"
_PARENTS = (Person.FATHER, Person.MOTHER)


def check_financial_chain(ctx: EvaluationContext) -> list[RuleResult]:
    tins = ctx.case.of_kind(TinCertificate)
    trades = ctx.case.of_kind(TradeLicense)

    gap = _structural_problem(tins, trades)
    if gap is not None:
        return [RuleResult(rule_id=r, outcome=gap[0], reason=gap[1]) for r in (CHAIN_01, CHAIN_02, CHAIN_03)]

    tin, trade = tins[0], trades[0]
    tin_name, trade_name = tin.taxpayer_name, trade.owner_name
    evidence = (
        ev(tin.doc_id, "taxpayer_name", tin_name),
        ev(trade.doc_id, "owner_name", trade_name),
    )

    unreadable = [
        f"{label} '{n.value}' read with low OCR confidence" if n.found else f"{label} not found by OCR"
        for label, n in (("TIN taxpayer name", tin_name), ("Trade License owner name", trade_name))
        if not n.is_reliable(ctx.threshold) or not normalize_name(n.value)
    ]
    if unreadable:
        reason = "; ".join(unreadable)
        return [
            RuleResult(rule_id=r, outcome=Outcome.FLAG, reason=reason, evidence=evidence)
            for r in (CHAIN_01, CHAIN_02, CHAIN_03)
        ]

    tin_id = identify(tin_name, ctx)
    trade_id = identify(trade_name, ctx)
    return [
        _chain_01(ctx, tin_name.value, trade_name.value, evidence),
        _chain_02(tin_id, trade_id, evidence),
        _chain_03(tin_id, trade_id, evidence),
    ]


def _structural_problem(tins: list, trades: list) -> tuple[Outcome, str] | None:
    missing = [label for label, docs in (("TIN Certificate", tins), ("Trade License", trades)) if not docs]
    if missing:
        return Outcome.FAIL, f"Financial chain cannot be established: no {' and no '.join(missing)}"
    extra = [label for label, docs in (("TIN Certificates", tins), ("Trade Licenses", trades)) if len(docs) > 1]
    if extra:
        return Outcome.FLAG, f"More than one {' and '.join(extra)} found; reviewer must pick which forms the chain"
    return None


def _chain_01(ctx: EvaluationContext, tin: str, trade: str, evidence) -> RuleResult:
    if normalize_name(tin) == normalize_name(trade):
        return RuleResult(
            rule_id=CHAIN_01,
            outcome=Outcome.PASS,
            reason=f"TIN taxpayer '{tin}' and Trade License owner '{trade}' are identical",
            evidence=evidence,
        )
    # A same-person affidavit for either parent can bridge a spelling difference (5.2).
    verdicts = [affidavit_bridge(ctx, p, tin, trade) for p in _PARENTS]
    for kind, why in verdicts:
        if kind is MatchKind.AFFIDAVIT:
            return RuleResult(
                rule_id=CHAIN_01,
                outcome=Outcome.PASS,
                reason=f"TIN taxpayer '{tin}' and Trade License owner '{trade}' differ in spelling, covered by {why}",
                evidence=evidence,
            )
    unsure = [why for kind, why in verdicts if kind is MatchKind.UNCERTAIN]
    if unsure:
        return RuleResult(
            rule_id=CHAIN_01,
            outcome=Outcome.FLAG,
            reason=f"TIN taxpayer '{tin}' and Trade License owner '{trade}' differ; {'; '.join(unsure)}",
            evidence=evidence,
        )
    return RuleResult(
        rule_id=CHAIN_01,
        outcome=Outcome.FAIL,
        reason=f"TIN taxpayer '{tin}' and Trade License owner '{trade}' are not identical",
        evidence=evidence,
    )


def _label(i: Identification) -> str:
    return i.person.value.title() if i.person else "nobody"


def _chain_02(tin: Identification, trade: Identification, evidence) -> RuleResult:
    def result(outcome: Outcome, reason: str) -> RuleResult:
        return RuleResult(rule_id=CHAIN_02, outcome=outcome, reason=reason, evidence=evidence)

    both = (tin, trade)
    if all(i.status is IdStatus.IDENTIFIED for i in both):
        if tin.person is trade.person and tin.person in _PARENTS:
            return result(Outcome.PASS, f"TIN and Trade License both belong to the {_label(tin)}")
        if tin.person in _PARENTS and trade.person in _PARENTS:
            return result(
                Outcome.FAIL,
                f"TIN belongs to the {_label(tin)} but Trade License belongs to the {_label(trade)}; "
                "both must belong to the same parent",
            )
        return result(
            Outcome.FAIL,
            f"TIN belongs to {_label(tin)}, Trade License to {_label(trade)}; both must belong to one parent",
        )
    # A document identified as nobody can never satisfy the chain, whatever the other says.
    unknown = [
        f"{doc} name matches no parent ({i.reason})"
        for doc, i in (("TIN", tin), ("Trade License", trade))
        if i.status is IdStatus.UNKNOWN
    ]
    if unknown:
        return result(Outcome.FAIL, "; ".join(unknown))
    unsure = [
        f"{doc}: {i.reason}" for doc, i in (("TIN", tin), ("Trade License", trade)) if i.status is not IdStatus.IDENTIFIED
    ]
    return result(Outcome.FLAG, "Could not confirm which parent owns the chain: " + "; ".join(unsure))


def _chain_03(tin: Identification, trade: Identification, evidence) -> RuleResult:
    def result(outcome: Outcome, reason: str) -> RuleResult:
        return RuleResult(rule_id=CHAIN_03, outcome=outcome, reason=reason, evidence=evidence)

    students = [doc for doc, i in (("TIN", tin), ("Trade License", trade)) if i.person is Person.STUDENT]
    if students:
        return result(Outcome.FAIL, f"{' and '.join(students)} in the student's name (StudentRef); must be a parent")
    unsure = [
        f"{doc}: {i.reason}"
        for doc, i in (("TIN", tin), ("Trade License", trade))
        if i.status in (IdStatus.AMBIGUOUS, IdStatus.UNCERTAIN)
    ]
    if unsure:
        return result(Outcome.FLAG, "Could not rule out the student's name: " + "; ".join(unsure))
    return result(Outcome.PASS, "Neither TIN nor Trade License is in the student's name")

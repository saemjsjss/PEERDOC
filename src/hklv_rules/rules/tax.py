"""Rulebook v2.5 section 4.9: Income Tax (TAX-01 .. TAX-04). Optional documents (REQ-10).

An absent Income Tax document is never a problem: TAX-01 PASSes and the per-document
rules (TAX-02/03 per Acknowledgement, TAX-04 per Challan) simply produce nothing.
The rulebook says to ignore the QR codes on the Income Tax Certificate and
Acknowledgement, so nothing here reads them.

TAX-04 needs the challan verification website. The rules engine never does I/O: the
online result arrives already filled in on `IncomeTaxChallan.online`, and this module
only interprets it.
"""

from __future__ import annotations

from decimal import Decimal

from ..context import EvaluationContext
from ..models import (
    Evidence,
    Extracted,
    IncomeTaxAcknowledgement,
    IncomeTaxCertificate,
    IncomeTaxChallan,
    OnlineStatus,
    Outcome,
    RuleResult,
)
from ._evidence import ev

TAX_01, TAX_02, TAX_03, TAX_04 = "TAX-01", "TAX-02", "TAX-03", "TAX-04"
ALL_RULES = (TAX_01, TAX_02, TAX_03, TAX_04)

MIN_TAX_PAID = Decimal("10000")  # BDT, TAX-02
MIN_TOTAL_INCOME = Decimal("5000000")  # BDT, TAX-03


def check_income_tax(ctx: EvaluationContext) -> list[RuleResult]:
    challans = ctx.case.of_kind(IncomeTaxChallan)
    acks = ctx.case.of_kind(IncomeTaxAcknowledgement)
    certs = ctx.case.of_kind(IncomeTaxCertificate)

    results = [_tax_01_presence(challans, acks, certs)]
    for ack in acks:
        results += [_tax_02_tax_limit(ack, ctx), _tax_03_wealth_limit(ack, ctx)]
    for challan in challans:
        results.append(_tax_04_challan(challan, ctx))
    return results


def _bdt(amount: Decimal) -> str:
    return f"{amount:,} BDT"


# --- TAX-01 Presence ------------------------------------------------------------------


def _tax_01_presence(
    challans: list[IncomeTaxChallan],
    acks: list[IncomeTaxAcknowledgement],
    certs: list[IncomeTaxCertificate],
) -> RuleResult:
    present = [
        f"{label} {', '.join(d.doc_id for d in docs)}"
        for label, docs in (
            ("Challan", challans),
            ("Acknowledgement", acks),
            ("Certificate", certs),
        )
        if docs
    ]
    if not present:
        return RuleResult(rule_id=TAX_01, outcome=Outcome.PASS, reason="No Income Tax documents submitted (optional)")
    return RuleResult(
        rule_id=TAX_01,
        outcome=Outcome.PASS,
        reason=f"Income Tax documents present: {'; '.join(present)}",
    )


# --- TAX-02 / TAX-03 minimum amounts on the Acknowledgement ---------------------------


def _minimum_rule(
    rule_id: str,
    doc_id: str,
    field: str,
    label: str,
    value: Extracted[Decimal],
    minimum: Decimal,
    ctx: EvaluationContext,
) -> RuleResult:
    """value >= minimum -> PASS; below it -> FLAG (as the rulebook says); unreadable -> FLAG."""
    evidence = (ev(doc_id, field, value),)
    where = f"Income Tax Acknowledgement {doc_id}"

    def result(outcome: Outcome, reason: str) -> RuleResult:
        return RuleResult(rule_id=rule_id, outcome=outcome, reason=reason, evidence=evidence)

    if not value.found:
        return result(Outcome.FLAG, f"{where}: {label} not found, so the {_bdt(minimum)} minimum can't be checked")
    if not value.is_reliable(ctx.threshold):
        return result(
            Outcome.FLAG,
            f"{where}: {label} '{value.value}' read with low OCR confidence ({value.confidence:.2f})",
        )
    if value.value >= minimum:
        return result(Outcome.PASS, f"{where}: {label} {_bdt(value.value)}, at least {_bdt(minimum)}")
    return result(Outcome.FLAG, f"{where}: {label} {_bdt(value.value)} is below {_bdt(minimum)}")


def _tax_02_tax_limit(ack: IncomeTaxAcknowledgement, ctx: EvaluationContext) -> RuleResult:
    return _minimum_rule(
        TAX_02, ack.doc_id, "total_tax_paid", "total tax paid", ack.total_tax_paid, MIN_TAX_PAID, ctx
    )


def _tax_03_wealth_limit(ack: IncomeTaxAcknowledgement, ctx: EvaluationContext) -> RuleResult:
    return _minimum_rule(
        TAX_03, ack.doc_id, "total_income", "total income shown", ack.total_income, MIN_TOTAL_INCOME, ctx
    )


# --- TAX-04 Challan verification ------------------------------------------------------


def _tax_04_challan(challan: IncomeTaxChallan, ctx: EvaluationContext) -> RuleResult:
    where = f"Income Tax Challan {challan.doc_id}"
    number, printed, online = challan.challan_number, challan.printed_amount, challan.online
    evidence = (ev(challan.doc_id, "challan_number", number), ev(challan.doc_id, "printed_amount", printed))

    def result(outcome: Outcome, reason: str) -> RuleResult:
        return RuleResult(rule_id=TAX_04, outcome=outcome, reason=reason, evidence=evidence)

    if not number.found or not number.value.strip():
        return result(Outcome.FLAG, f"{where}: challan number not found, so it can't be verified online")
    if not number.is_reliable(ctx.threshold):
        return result(
            Outcome.FLAG,
            f"{where}: challan number '{number.value}' read with low OCR confidence ({number.confidence:.2f})",
        )
    label = f"{where} (No. {number.value})"
    if online is None or online.status is OnlineStatus.NOT_RUN:
        return result(Outcome.FLAG, f"{label}: not verified online: online checks not enabled")
    if online.status is OnlineStatus.UNAVAILABLE:
        detail = online.detail or "no detail given"
        return result(Outcome.FLAG, f"{label}: internet check failed: {detail}")
    if online.status is OnlineStatus.NOT_FOUND:
        detail = f" ({online.detail})" if online.detail else ""
        return result(Outcome.FAIL, f"{label}: the challan site has no such challan{detail}")

    # VERIFIED: compare the website amount with the printed amount.
    evidence += (
        Evidence(
            doc_id=challan.doc_id,
            field="online.amount",
            value=None if online.amount is None else str(online.amount),
        ),
    )
    if not printed.found:
        return result(Outcome.FLAG, f"{label}: verified online, but the printed amount was not found")
    if not printed.is_reliable(ctx.threshold):
        return result(
            Outcome.FLAG,
            f"{label}: verified online, but the printed amount '{printed.value}' was read with low OCR "
            f"confidence ({printed.confidence:.2f})",
        )
    if online.amount is None:
        return result(Outcome.FLAG, f"{label}: verified online, but the website showed no amount")
    if online.amount == printed.value:
        return result(Outcome.PASS, f"{label}: website amount matches printed amount ({_bdt(printed.value)})")
    return result(
        Outcome.FAIL,
        f"{label}: website amount {_bdt(online.amount)} does not match printed amount {_bdt(printed.value)}",
    )

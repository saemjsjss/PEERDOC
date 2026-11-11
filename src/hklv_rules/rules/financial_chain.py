"""Rulebook v2.5 section 5.1: the financial chain (strict parent match).

The TIN Taxpayer and the holder of the income document must be the same parent. The
income document is the Trade License or, instead of it, an Employment Certificate
(REQ-06). Bank documents are deliberately NOT part of this chain.

Overlaps removed 2026-11-12: CHAIN-01 (TIN name == income-document name) was the same check
as TIN-03, and the income document being the student's is TRADE-04 / EMP-05's job, so
CHAIN-03 checks only the TIN.
"""

from __future__ import annotations

from ..context import EvaluationContext
from ..identity import Identification, IdStatus, identify
from ..models import EmploymentCertificate, Extracted, Outcome, Person, RuleResult, TinCertificate, TradeLicense
from ..models.common import Frozen
from ..names import normalize_name
from ._evidence import ev

CHAIN_02, CHAIN_03 = "CHAIN-02", "CHAIN-03"
_PARENTS = (Person.FATHER, Person.MOTHER)


class _Income(Frozen):
    """The chain's second link: a Trade License (owner) or an Employment Certificate (employee)."""

    doc_id: str
    label: str
    holder: str
    field: str
    name: Extracted[str]

    @classmethod
    def of(cls, doc: TradeLicense | EmploymentCertificate) -> _Income:
        if isinstance(doc, TradeLicense):
            return cls(doc_id=doc.doc_id, label="Trade License", holder="owner", field="owner_name", name=doc.owner_name)
        return cls(
            doc_id=doc.doc_id,
            label="Employment Certificate",
            holder="employee",
            field="employee_name",
            name=doc.employee_name,
        )

    @property
    def describe(self) -> str:
        return f"{self.label} {self.holder}"


def check_financial_chain(ctx: EvaluationContext) -> list[RuleResult]:
    tins = ctx.case.of_kind(TinCertificate)
    incomes = [_Income.of(d) for d in [*ctx.case.of_kind(TradeLicense), *ctx.case.of_kind(EmploymentCertificate)]]

    gap = _structural_problem(tins, incomes)
    if gap is not None and gap[0] is Outcome.FAIL:
        return [RuleResult(rule_id=r, outcome=gap[0], reason=gap[1]) for r in (CHAIN_02, CHAIN_03)]
    if gap is not None:
        return _gated(ctx, tins, incomes, gap[1])

    tin, income = tins[0], incomes[0]
    tin_name, income_name = tin.taxpayer_name, income.name
    evidence = (
        ev(tin.doc_id, "taxpayer_name", tin_name),
        ev(income.doc_id, income.field, income_name),
    )

    unreadable = [
        f"{label} '{n.value}' read with low OCR confidence" if n.found else f"{label} not found by OCR"
        for label, n in (("TIN taxpayer name", tin_name), (f"{income.describe} name", income_name))
        if not n.is_reliable(ctx.threshold) or not normalize_name(n.value)
    ]
    if unreadable:
        return _gated(ctx, tins, incomes, "; ".join(unreadable), evidence)

    tin_id = identify(tin_name, ctx)
    income_id = identify(income_name, ctx)
    return [
        _chain_02(tin_id, income_id, income.label, evidence),
        _chain_03(tin_id, evidence),
    ]


def _settled(names: list[Extracted[str]], ctx: EvaluationContext) -> Person | IdStatus | None:
    """What a group of candidate documents certainly says on its own, if anything.

    Returns Person.STUDENT if every document is reliably the student's, IdStatus.UNKNOWN if
    every one reliably matches nobody, else None. With several candidates the reviewer may
    pick any, so only a verdict shared by all of them is certain.
    """
    verdicts = set()
    for n in names:
        if not n.is_reliable(ctx.threshold) or not normalize_name(n.value):
            return None
        i = identify(n, ctx)
        if i.status is IdStatus.IDENTIFIED and i.person is Person.STUDENT:
            verdicts.add(Person.STUDENT)
        elif i.status is IdStatus.UNKNOWN:
            verdicts.add(IdStatus.UNKNOWN)
        else:
            return None
    return verdicts.pop() if len(verdicts) == 1 else None


def _gated(
    ctx: EvaluationContext, tins: list, incomes: list[_Income], why: str, evidence=()
) -> list[RuleResult]:
    """The chain can't be compared (a link is unreadable or duplicated), so the rules FLAG.

    CHAIN-02 and CHAIN-03 still FAIL when one link on its own already decides them: a link
    reliably in the student's name, or one that reliably matches no family member.
    """
    labels = {i.label for i in incomes}
    income_label = labels.pop() if len(labels) == 1 else "Trade License/Employment Certificate"
    settled = [
        (label, v)
        for label, v in (
            ("TIN", _settled([t.taxpayer_name for t in tins], ctx)),
            (income_label, _settled([i.name for i in incomes], ctx)),
        )
        if v is not None
    ]
    students = [label for label, v in settled if v is Person.STUDENT]
    strangers = [label for label, v in settled if v is IdStatus.UNKNOWN]

    def flag(rule_id: str) -> RuleResult:
        return RuleResult(rule_id=rule_id, outcome=Outcome.FLAG, reason=why, evidence=evidence)

    def fail(rule_id: str, reason: str) -> RuleResult:
        return RuleResult(rule_id=rule_id, outcome=Outcome.FAIL, reason=f"{reason} ({why})", evidence=evidence)

    out = []
    if students or strangers:
        parts = [f"{label} is in the student's name" for label in students]
        parts += [f"{label} name matches no parent" for label in strangers]
        out.append(fail(CHAIN_02, "; ".join(parts) + "; the chain must belong to one parent"))
    else:
        out.append(flag(CHAIN_02))
    if "TIN" in students:
        out.append(fail(CHAIN_03, "TIN in the student's name (StudentRef); must be a parent"))
    else:
        out.append(flag(CHAIN_03))
    return out


def _structural_problem(tins: list, incomes: list[_Income]) -> tuple[Outcome, str] | None:
    groups = (("TIN Certificate", tins), ("Trade License or Employment Certificate", incomes))
    missing = [label for label, docs in groups if not docs]
    if missing:
        return Outcome.FAIL, f"Financial chain cannot be established: no {' and no '.join(missing)}"
    extra = [label for label, docs in groups if len(docs) > 1]
    if extra:
        return (
            Outcome.FLAG,
            f"More than one {' and more than one '.join(extra)} found; reviewer must pick which forms the chain",
        )
    return None


def _label(i: Identification) -> str:
    return i.person.value.title() if i.person else "nobody"


def _chain_02(tin: Identification, other: Identification, label: str, evidence) -> RuleResult:
    def result(outcome: Outcome, reason: str) -> RuleResult:
        return RuleResult(rule_id=CHAIN_02, outcome=outcome, reason=reason, evidence=evidence)

    pair = (("TIN", tin), (label, other))
    if all(i.status is IdStatus.IDENTIFIED for _, i in pair):
        if tin.person is other.person and tin.person in _PARENTS:
            return result(Outcome.PASS, f"TIN and {label} both belong to the {_label(tin)}")
        if tin.person in _PARENTS and other.person in _PARENTS:
            return result(
                Outcome.FAIL,
                f"TIN belongs to the {_label(tin)} but {label} belongs to the {_label(other)}; "
                "both must belong to the same parent",
            )
        return result(
            Outcome.FAIL,
            f"TIN belongs to {_label(tin)}, {label} to {_label(other)}; both must belong to one parent",
        )
    # A document identified as nobody can never satisfy the chain, whatever the other says.
    unknown = [f"{doc} name matches no parent ({i.reason})" for doc, i in pair if i.status is IdStatus.UNKNOWN]
    if unknown:
        return result(Outcome.FAIL, "; ".join(unknown))
    unsure = [f"{doc}: {i.reason}" for doc, i in pair if i.status is not IdStatus.IDENTIFIED]
    return result(Outcome.FLAG, "Could not confirm which parent owns the chain: " + "; ".join(unsure))


def _chain_03(tin: Identification, evidence) -> RuleResult:
    def result(outcome: Outcome, reason: str) -> RuleResult:
        return RuleResult(rule_id=CHAIN_03, outcome=outcome, reason=reason, evidence=evidence)

    if tin.person is Person.STUDENT:
        return result(Outcome.FAIL, "TIN in the student's name (StudentRef); must be a parent")
    if tin.status in (IdStatus.AMBIGUOUS, IdStatus.UNCERTAIN):
        return result(Outcome.FLAG, f"Could not rule out the student's name: TIN: {tin.reason}")
    return result(Outcome.PASS, "TIN is not in the student's name")

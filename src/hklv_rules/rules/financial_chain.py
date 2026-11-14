"""RULES-v9 section 5.1: the financial chain (CHAIN-02).

The TIN, the income document (Trade License or Employment Certificate) and every Bank
Solvency must belong to the same parent. Each document's own rule already decides whose it
is (TIN-03, TRADE-04, EMP-05, BANK-01): a document that is the student's, a stranger's or
uncertain is reported there, once. CHAIN-02 compares only the documents those rules
assigned to a parent, and gives no result when a link has no such document (the missing
document is REQ-05 / REQ-06 / REQ-07's job, an unassigned one its own rule's).

v8's CHAIN-03 (TIN in the student's name) and CHAIN-04 (bank account holder) are merged
into this rule and TIN-03 (RULES-v9); CHAIN-01 was deleted in v6. Their IDs are not reused.
"""

from __future__ import annotations

from ..context import EvaluationContext
from ..models import (
    BankSolvency,
    EmploymentCertificate,
    Outcome,
    Person,
    RuleResult,
    TinCertificate,
    TradeLicense,
)
from ._evidence import ev
from ._shared import assign_by_name

CHAIN_02 = "CHAIN-02"
ALL_RULES = (CHAIN_02,)
_PARENTS = (Person.FATHER, Person.MOTHER)


def _owners(ctx: EvaluationContext, label: str, docs: list[tuple[str, str, object]]) -> dict[str, Person]:
    """doc_id -> parent, for the documents assigned to a parent by name (PASS only)."""
    assignment = assign_by_name("CHAIN", label, docs, ctx, allowed=_PARENTS)
    return {doc_id: p for p in _PARENTS for doc_id in assignment.doc_ids_for(p)}


def check_financial_chain(ctx: EvaluationContext) -> list[RuleResult]:
    tins = ctx.case.of_kind(TinCertificate)
    trades = ctx.case.of_kind(TradeLicense)
    employments = ctx.case.of_kind(EmploymentCertificate)
    solvencies = ctx.case.of_kind(BankSolvency)

    tin_of = _owners(ctx, "TIN Certificate", [(t.doc_id, "taxpayer_name", t.taxpayer_name) for t in tins])
    income_of = {
        **_owners(ctx, "Trade License", [(t.doc_id, "owner_name", t.owner_name) for t in trades]),
        **_owners(ctx, "Employment Certificate", [(e.doc_id, "employee_name", e.employee_name) for e in employments]),
    }
    bank_of = _owners(ctx, "Bank Solvency", [(s.doc_id, "account_holder", s.account_holder) for s in solvencies])
    if not tin_of or not income_of or not bank_of:
        return []  # a link has no document assigned to a parent: reported by its own rule

    evidence = (
        *(ev(t.doc_id, "taxpayer_name", t.taxpayer_name) for t in tins if t.doc_id in tin_of),
        *(ev(t.doc_id, "owner_name", t.owner_name) for t in trades if t.doc_id in income_of),
        *(ev(e.doc_id, "employee_name", e.employee_name) for e in employments if e.doc_id in income_of),
        *(ev(s.doc_id, "account_holder", s.account_holder) for s in solvencies if s.doc_id in bank_of),
    )

    def result(outcome: Outcome, reason: str) -> list[RuleResult]:
        return [RuleResult(rule_id=CHAIN_02, outcome=outcome, reason=reason, evidence=evidence)]

    def who(owner: dict[str, Person]) -> str:
        return ", ".join(f"{doc_id} = {p.value.title()}" for doc_id, p in owner.items())

    candidates = [p for p in _PARENTS if p in tin_of.values() and p in income_of.values()]
    banks = set(bank_of.values())
    if not candidates:
        return result(
            Outcome.FAIL,
            f"TIN ({who(tin_of)}) and income document ({who(income_of)}) belong to different parents; "
            "the chain must belong to one parent",
        )
    if len(candidates) == 1:
        parent = candidates[0]
        others = {d: p for d, p in bank_of.items() if p is not parent}
        if others:
            return result(
                Outcome.FAIL,
                f"TIN and income document belong to the {parent.value.lower()}, but Bank Solvency "
                f"{who(others)}; every account holder must be the same parent",
            )
        return result(Outcome.PASS, f"TIN, income document and bank account all belong to the {parent.value.lower()}")
    # Both parents have a TIN and an income document: the bank decides, if it names one parent.
    if len(banks) == 1:
        parent = banks.pop()
        return result(Outcome.PASS, f"TIN, income document and bank account all belong to the {parent.value.lower()}")
    return result(
        Outcome.FLAG,
        f"Both parents have a TIN and an income document and the bank accounts are split ({who(bank_of)}); "
        "reviewer must pick which parent forms the chain",
    )

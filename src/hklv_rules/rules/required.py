"""Rulebook v2.5 section 3: required documents (REQ-01 .. REQ-10).

REQ-10: Income Tax, the Student NID and IELTS/TOPIK are optional; absent is PASS.

REQ-06 accepts a Trade License OR an Employment Certificate. REQ-08 / REQ-09 accept a
parent's NID OR that parent's Death Certificate; both are matched to the parent by name
(NID-ASSIGN, DEATH-01), so an NID that belongs to someone else does not count.
"""

from __future__ import annotations

from ..context import EvaluationContext
from ..models import (
    BankSolvency,
    BankStatement,
    BirthCertificate,
    EmploymentCertificate,
    FamilyRelationshipCertificate,
    IncomeTaxAcknowledgement,
    IncomeTaxCertificate,
    IncomeTaxChallan,
    LanguageTest,
    Outcome,
    Passport,
    Person,
    Photo,
    RuleResult,
    TinCertificate,
    TradeLicense,
)
from ._shared import Assignment


def _has(ctx: EvaluationContext, *kinds: type) -> bool:
    return any(ctx.case.of_kind(k) for k in kinds)


def _presence(rule_id: str, present: bool, missing_reason: str, found_reason: str) -> RuleResult:
    if present:
        return RuleResult(rule_id=rule_id, outcome=Outcome.PASS, reason=found_reason)
    return RuleResult(rule_id=rule_id, outcome=Outcome.FAIL, reason=missing_reason)


def check_required_documents(ctx: EvaluationContext, nids: Assignment, deaths: Assignment) -> list[RuleResult]:
    has_solvency, has_statement = _has(ctx, BankSolvency), _has(ctx, BankStatement)
    missing_bank = [label for label, ok in (("Bank Solvency", has_solvency), ("Bank Statement", has_statement)) if not ok]
    return [
        _presence("REQ-01", _has(ctx, Passport), "No Passport", "Passport present"),
        _presence("REQ-02", _has(ctx, Photo), "No Photo", "Photo present"),
        _presence("REQ-03", _has(ctx, BirthCertificate), "No Birth Certificate", "Birth Certificate present"),
        _presence(
            "REQ-04",
            _has(ctx, FamilyRelationshipCertificate),
            "No Family Relationship Certificate",
            "Family Relationship Certificate present",
        ),
        _presence(
            "REQ-05",
            not missing_bank,
            f"No {' and no '.join(missing_bank)}",
            "Bank Solvency and Bank Statement present",
        ),
        _presence(
            "REQ-06",
            _has(ctx, TradeLicense, EmploymentCertificate),
            "No Trade License and no Employment Certificate",
            "Trade License or Employment Certificate present",
        ),
        _presence("REQ-07", _has(ctx, TinCertificate), "No TIN Certificate", "TIN Certificate present"),
        _parent_identity("REQ-08", Person.FATHER, nids, deaths),
        _parent_identity("REQ-09", Person.MOTHER, nids, deaths),
        _optional(ctx, nids),
    ]


def _parent_identity(rule_id: str, parent: Person, nids: Assignment, deaths: Assignment) -> RuleResult:
    who = parent.value.title()
    nid_ids, death_ids = nids.doc_ids_for(parent), deaths.doc_ids_for(parent)
    if nid_ids or death_ids:
        found = [f"{who} NID ({', '.join(nid_ids)})"] if nid_ids else []
        found += [f"{who} Death Certificate ({', '.join(death_ids)})"] if death_ids else []
        return RuleResult(rule_id=rule_id, outcome=Outcome.PASS, reason=" and ".join(found) + " present")
    unresolved = nids.possible_for(parent) + deaths.possible_for(parent)
    if unresolved:
        return RuleResult(
            rule_id=rule_id,
            outcome=Outcome.FLAG,
            reason=f"No {who} NID or Death Certificate confirmed; could not assign {', '.join(unresolved)}, "
            f"which may be the {who.lower()}'s",
        )
    return RuleResult(
        rule_id=rule_id, outcome=Outcome.FAIL, reason=f"No {who} NID and no {who} Death Certificate"
    )


def _optional(ctx: EvaluationContext, nids: Assignment) -> RuleResult:
    tax = _has(ctx, IncomeTaxChallan, IncomeTaxAcknowledgement, IncomeTaxCertificate)
    student_nid = bool(nids.doc_ids_for(Person.STUDENT))
    language = _has(ctx, LanguageTest)
    notes = [
        f"Income Tax {'present' if tax else 'not submitted'}",
        f"Student NID {'present' if student_nid else 'not submitted'}",
        f"IELTS/TOPIK {'present' if language else 'not submitted'}",
    ]
    return RuleResult(rule_id="REQ-10", outcome=Outcome.PASS, reason="Optional documents: " + "; ".join(notes))

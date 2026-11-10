"""Employment Certificate rules (EMP-01 .. EMP-05). DRAFT: not in Rulebook v2.5.

The rulebook allows an Employment Certificate instead of a Trade License (REQ-06) and
puts both under section 4.6, but only spells out TRADE-01..04. These rules mirror them,
with two differences that suit an employer's letter rather than a licence:
  * EMP-03: the letter must be recent (issued within 3 months), not "current fiscal year".
  * EMP-04: the letter must say the person is employed NOW; an experience or release
    letter does not show a current income.
"""

from __future__ import annotations

from ..context import EvaluationContext
from ..models import EmploymentCertificate, Outcome, Person, RuleResult
from ._evidence import ev
from ._shared import assign_by_name, notary_rule, recency_rule, translation_rule

EMP_01, EMP_02, EMP_03, EMP_04, EMP_05 = "EMP-01", "EMP-02", "EMP-03", "EMP-04", "EMP-05"
VALIDITY_MONTHS = 3


def check_employment(ctx: EvaluationContext) -> list[RuleResult]:
    """Runs only when an Employment Certificate was submitted; absence is REQ-06's job."""
    results: list[RuleResult] = []
    for cert in ctx.case.of_kind(EmploymentCertificate):
        results += [
            translation_rule(EMP_01, cert.doc_id, cert.language, cert.has_english_translation, ctx),
            notary_rule(EMP_02, cert.doc_id, cert.notary, ctx),
            recency_rule(EMP_03, cert.doc_id, [("issue_date", cert.issue_date)], VALIDITY_MONTHS, ctx, "Issue date"),
            _emp_04_current(cert, ctx),
            _emp_05_employee(cert, ctx),
        ]
    return results


def _emp_04_current(cert: EmploymentCertificate, ctx: EvaluationContext) -> RuleResult:
    evidence = (ev(cert.doc_id, "currently_employed", cert.currently_employed),)
    current = ctx.tri_state(cert.currently_employed)
    if current is True:
        return RuleResult(rule_id=EMP_04, outcome=Outcome.PASS, reason="States current employment", evidence=evidence)
    if current is False:
        return RuleResult(
            rule_id=EMP_04,
            outcome=Outcome.FAIL,
            reason="Does not state current employment (experience or release letter)",
            evidence=evidence,
        )
    return RuleResult(
        rule_id=EMP_04,
        outcome=Outcome.FLAG,
        reason="Could not confirm the letter states current employment",
        evidence=evidence,
    )


def _emp_05_employee(cert: EmploymentCertificate, ctx: EvaluationContext) -> RuleResult:
    """Employee must be the father or mother; the student, or anyone else, FAILs."""
    assignment = assign_by_name(
        EMP_05,
        "Employment Certificate",
        [(cert.doc_id, "employee_name", cert.employee_name)],
        ctx,
        allowed=(Person.FATHER, Person.MOTHER),
        unknown_reason="is for someone who is not the father or mother",
    )
    return assignment.results[0]

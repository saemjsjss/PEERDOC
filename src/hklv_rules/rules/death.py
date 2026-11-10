"""Death Certificate rules (DEATH-01 .. DEATH-04). DRAFT: not in Rulebook v2.5.

A Death Certificate stands in for a deceased parent's NID (REQ-08 / REQ-09), so it gets
the checks the NID would have had:
  * DEATH-01 (Assignment): deceased name must match FatherRef or MotherRef. The student
    or anyone else FAILs; an unreadable or ambiguous name FLAGs.
  * DEATH-02 (Format): if Bangla, must have an English translation.
  * DEATH-03 (Notary): must be notarised (Notary Public/Advocate text and a stamp).
  * DEATH-04 (Date): a date of death must be readable and not after the evaluation date.
  * DEATH-05 (Consistency): no financial document may present the deceased parent as a
    living sponsor. An Employment Certificate for them issued after the date of death
    FAILs; any other Employment Certificate, Trade License or TIN in their name FLAGs.
"""

from __future__ import annotations

from ..context import EvaluationContext
from ..identity import IdStatus, identify
from ..models import (
    DeathCertificate,
    EmploymentCertificate,
    Outcome,
    Person,
    RuleResult,
    TinCertificate,
    TradeLicense,
)
from ._evidence import ev
from ._shared import Assignment, assign_by_name, notary_rule, translation_rule

DEATH_01, DEATH_02, DEATH_03, DEATH_04, DEATH_05 = "DEATH-01", "DEATH-02", "DEATH-03", "DEATH-04", "DEATH-05"
_PARENTS = (Person.FATHER, Person.MOTHER)


def check_death_certificates(ctx: EvaluationContext) -> Assignment:
    """Assigns each Death Certificate to a parent; `results` holds every DEATH-xx result."""
    certs = ctx.case.of_kind(DeathCertificate)
    assignment = assign_by_name(
        DEATH_01,
        "Death Certificate",
        [(c.doc_id, "deceased_name", c.deceased_name) for c in certs],
        ctx,
        allowed=(Person.FATHER, Person.MOTHER),
        unknown_reason="is for someone who is not the father or mother",
    )
    results = list(assignment.results)
    for cert in certs:
        results += [
            translation_rule(DEATH_02, cert.doc_id, cert.language, cert.has_english_translation, ctx),
            notary_rule(DEATH_03, cert.doc_id, cert.notary, ctx),
            _death_04_date(cert, ctx),
        ]
    for parent in _PARENTS:
        for doc_id in assignment.doc_ids_for(parent):
            cert = next(c for c in certs if c.doc_id == doc_id)
            results.append(_death_05_consistency(cert, parent, ctx))
    return assignment.model_copy(update={"results": tuple(results)})


def _death_04_date(cert: DeathCertificate, ctx: EvaluationContext) -> RuleResult:
    evidence = (ev(cert.doc_id, "date_of_death", cert.date_of_death),)

    def result(outcome: Outcome, reason: str) -> RuleResult:
        return RuleResult(rule_id=DEATH_04, outcome=outcome, reason=reason, evidence=evidence)

    d = cert.date_of_death
    if not d.found:
        return result(Outcome.FLAG, "No date of death found")
    if not d.is_reliable(ctx.threshold):
        return result(Outcome.FLAG, "Date of death read with low OCR confidence")
    today = ctx.case.evaluation_date
    if d.value > today:
        return result(Outcome.FLAG, f"Date of death {d.value:%d-%m-%Y} is after the evaluation date {today:%d-%m-%Y}")
    return result(Outcome.PASS, f"Date of death {d.value:%d-%m-%Y}")


def _death_05_consistency(cert: DeathCertificate, parent: Person, ctx: EvaluationContext) -> RuleResult:
    who = parent.value.lower()
    died = cert.date_of_death.value if cert.date_of_death.is_reliable(ctx.threshold) else None
    holders = [
        (e.doc_id, "Employment Certificate", "employee_name", e.employee_name, e)
        for e in ctx.case.of_kind(EmploymentCertificate)
    ]
    holders += [(t.doc_id, "Trade License", "owner_name", t.owner_name, None) for t in ctx.case.of_kind(TradeLicense)]
    holders += [(t.doc_id, "TIN Certificate", "taxpayer_name", t.taxpayer_name, None) for t in ctx.case.of_kind(TinCertificate)]

    fails: list[str] = []
    flags: list[str] = []
    evidence = [ev(cert.doc_id, "date_of_death", cert.date_of_death)]
    for doc_id, label, field, name, emp in holders:
        i = identify(name, ctx, candidates=_PARENTS)
        if not (i.status is IdStatus.IDENTIFIED and i.person is parent):
            continue
        evidence.append(ev(doc_id, field, name))
        issued = emp.issue_date.value if emp is not None and emp.issue_date.is_reliable(ctx.threshold) else None
        if emp is not None and died and issued and issued > died:
            fails.append(f"{label} {doc_id} was issued {issued:%d-%m-%Y}, after the {who}'s death on {died:%d-%m-%Y}")
        else:
            flags.append(f"{label} {doc_id} is in the deceased {who}'s name")

    def result(outcome: Outcome, reason: str) -> RuleResult:
        return RuleResult(rule_id=DEATH_05, outcome=outcome, reason=reason, evidence=tuple(evidence))

    if fails:
        return result(Outcome.FAIL, "; ".join(fails + flags))
    if flags:
        return result(Outcome.FLAG, "; ".join(flags) + "; check who the living sponsor is")
    return result(Outcome.PASS, f"No financial document presents the deceased {who} as a sponsor")

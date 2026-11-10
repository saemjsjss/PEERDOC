"""Rulebook v2.5 section 2.2: NID auto-assignment.

Every NID (Old or Digital) is assigned to the student, father or mother by its
cardholder name. A name matching nobody FAILs ("unknown person or sibling").
"""

from __future__ import annotations

from ..context import EvaluationContext
from ..identity import IdStatus, MatchKind, identify
from ..models import NationalId, Outcome, Person, RuleResult
from ..models.common import Frozen
from ._evidence import ev

RULE_ID = "NID-ASSIGN"


class NidAssignment(Frozen):
    assigned: dict[Person, tuple[str, ...]]
    results: tuple[RuleResult, ...]

    def doc_ids_for(self, person: Person) -> tuple[str, ...]:
        return self.assigned.get(person, ())


def assign_nids(ctx: EvaluationContext) -> NidAssignment:
    assigned: dict[Person, list[str]] = {p: [] for p in Person}
    results: list[RuleResult] = []

    for nid in ctx.case.of_kind(NationalId):
        evidence = (ev(nid.doc_id, "cardholder_name", nid.cardholder_name),)
        ident = identify(nid.cardholder_name, ctx)

        if ident.status is IdStatus.IDENTIFIED:
            assigned[ident.person].append(nid.doc_id)
            how = " (spelling difference covered by affidavit)" if ident.via is MatchKind.AFFIDAVIT else ""
            outcome, reason = Outcome.PASS, f"NID {nid.doc_id} assigned to {ident.person.value.title()}{how}: {ident.reason}"
        elif ident.status is IdStatus.UNKNOWN:
            outcome, reason = (
                Outcome.FAIL,
                f"NID {nid.doc_id} belongs to an unknown person or sibling: {ident.reason}",
            )
        else:  # AMBIGUOUS or UNCERTAIN
            outcome, reason = (
                Outcome.FLAG,
                f"NID {nid.doc_id} could not be assigned with certainty: {ident.reason}",
            )
        results.append(RuleResult(rule_id=RULE_ID, outcome=outcome, reason=reason, evidence=evidence))

    for person, doc_ids in assigned.items():
        if len(doc_ids) > 1:
            results.append(
                RuleResult(
                    rule_id=RULE_ID,
                    outcome=Outcome.FLAG,
                    reason=f"More than one NID assigned to {person.value.title()}: {', '.join(doc_ids)}",
                )
            )

    return NidAssignment(
        assigned={p: tuple(ids) for p, ids in assigned.items() if ids},
        results=tuple(results),
    )

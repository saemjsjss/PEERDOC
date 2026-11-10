"""Rulebook v2.5 section 2.2: NID auto-assignment.

Every NID (Old or Digital) is assigned to the student, father or mother by its
cardholder name. A name matching nobody FAILs ("unknown person or sibling").
"""

from __future__ import annotations

from ..context import EvaluationContext
from ..models import NationalId
from ._shared import Assignment, assign_by_name

RULE_ID = "NID-ASSIGN"

NidAssignment = Assignment


def assign_nids(ctx: EvaluationContext) -> Assignment:
    return assign_by_name(
        RULE_ID,
        "NID",
        [(n.doc_id, "cardholder_name", n.cardholder_name) for n in ctx.case.of_kind(NationalId)],
        ctx,
        unknown_reason="belongs to an unknown person or sibling",
    )

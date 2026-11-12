"""RULES-v5 Section 4.12: notary and translator dates (STAMP-01).

Translation and notarisation may be on different days. Each notary or translator date
read with at least 85% confidence must be within 3 months of the evaluation date
(inclusive). A date read with less confidence, or one after the evaluation date (a
misread), is ignored: no result at all, not a FLAG.
"""

from __future__ import annotations

from ..context import EvaluationContext
from ..models import Outcome, RuleResult
from ._evidence import ev
from ._shared import subtract_months

STAMP_01 = "STAMP-01"
ALL_RULES = (STAMP_01,)

STAMP_MIN_CONFIDENCE = 0.85  # the owner's figure, separate from the 0.90 threshold
_VALIDITY_MONTHS = 3


def check_stamp_dates(ctx: EvaluationContext) -> list[RuleResult]:
    today = ctx.case.evaluation_date
    cutoff = subtract_months(today, _VALIDITY_MONTHS)
    results = []
    for doc in ctx.case.documents:
        for field, who, dates in (
            ("notary_dates", "notary", doc.notary_dates),
            ("translation_dates", "translator", doc.translation_dates),
        ):
            for d in dates:
                if not d.is_reliable(STAMP_MIN_CONFIDENCE) or d.value > today:
                    continue
                if d.value >= cutoff:
                    outcome, why = Outcome.PASS, f"is within {_VALIDITY_MONTHS} months (on or after {cutoff:%d-%m-%Y})"
                else:
                    outcome, why = Outcome.FAIL, f"is older than {_VALIDITY_MONTHS} months (cutoff {cutoff:%d-%m-%Y})"
                results.append(
                    RuleResult(
                        rule_id=STAMP_01,
                        outcome=outcome,
                        reason=f"{doc.doc_id}: {who} date {d.value:%d-%m-%Y} {why}",
                        evidence=(ev(doc.doc_id, field, d),),
                    )
                )
    return results

"""Rulebook v2.5 section 4.2: National ID (NID-01 .. NID-03).

One result per rule per NationalId document, whether or not it was assigned to someone
(assignment itself is NID-ASSIGN's job). Each reason names the NID and its owner.
  * NID-01 (Translation): must have an English translation page. Missing -> FAIL,
    unreadable -> FLAG.
  * NID-02 (Notary): Notary Public/Advocate text AND a stamp. Missing -> FAIL.
  * NID-03 (Number match): number on card vs number on the translation. Exact -> PASS,
    1-2 digits differ -> FLAG, 3+ -> FAIL. No translation to compare against -> FLAG
    (NID-01 already FAILs that case).
No NIDs -> no results: REQ-08/09 handle missing parent identity, and a student NID is optional.
"""

from __future__ import annotations

from ..context import EvaluationContext
from ..models import NationalId, Outcome, RuleResult
from ._evidence import ev
from ._shared import Assignment, notary_rule, number_match_rule

NID_01, NID_02, NID_03 = "NID-01", "NID-02", "NID-03"
ALL_RULES = (NID_01, NID_02, NID_03)


def check_nids(ctx: EvaluationContext, nids: Assignment) -> list[RuleResult]:
    results: list[RuleResult] = []
    for nid in ctx.case.of_kind(NationalId):
        label = _label(nid.doc_id, nids)
        results += [
            _nid_01_translation(nid, label, ctx),
            _prefixed(notary_rule(NID_02, nid.doc_id, nid.notary, ctx), label),
            _nid_03_number(nid, label, ctx),
        ]
    return results


def _label(doc_id: str, nids: Assignment) -> str:
    owners = [person.value.title() for person, ids in nids.assigned.items() if doc_id in ids]
    return f"NID {doc_id} ({', '.join(owners) if owners else 'unassigned'})"


def _prefixed(result: RuleResult, label: str) -> RuleResult:
    return result.model_copy(update={"reason": f"{label}: {result.reason}"})


def _nid_01_translation(nid: NationalId, label: str, ctx: EvaluationContext) -> RuleResult:
    evidence = (ev(nid.doc_id, "has_english_translation", nid.has_english_translation),)
    translated = ctx.tri_state(nid.has_english_translation)
    if translated is True:
        outcome, reason = Outcome.PASS, "English translation page present"
    elif translated is False:
        outcome, reason = Outcome.FAIL, "no English translation page"
    elif nid.has_english_translation.found:
        outcome, reason = Outcome.FLAG, "English translation page could not be confirmed (low OCR confidence)"
    else:
        outcome, reason = Outcome.FLAG, "could not determine whether an English translation page is present"
    return RuleResult(rule_id=NID_01, outcome=outcome, reason=f"{label}: {reason}", evidence=evidence)


def _nid_03_number(nid: NationalId, label: str, ctx: EvaluationContext) -> RuleResult:
    if ctx.tri_state(nid.has_english_translation) is False:
        return RuleResult(
            rule_id=NID_03,
            outcome=Outcome.FLAG,
            reason=f"{label}: no translation to compare against, so the NID number can't be checked",
            evidence=(
                ev(nid.doc_id, "number_on_card", nid.number_on_card),
                ev(nid.doc_id, "has_english_translation", nid.has_english_translation),
            ),
        )
    result = number_match_rule(
        NID_03,
        nid.doc_id,
        "NID number",
        ("number_on_card", nid.number_on_card),
        ("number_on_translation", nid.number_on_translation),
        ctx,
    )
    return _prefixed(result, label)

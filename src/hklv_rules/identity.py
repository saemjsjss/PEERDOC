"""Comparing an extracted name with the anchors, including affidavit bridging (5.2).

Affidavit bridging applies everywhere a name is compared, NID assignment included.
"""

from __future__ import annotations

from enum import Enum

from .context import EvaluationContext
from .models import Affidavit, Extracted, Person
from .models.common import Frozen
from .names import normalize_name, same_name

ALL_PEOPLE = (Person.STUDENT, Person.FATHER, Person.MOTHER)


class MatchKind(str, Enum):
    EXACT = "EXACT"
    AFFIDAVIT = "AFFIDAVIT"
    MISMATCH = "MISMATCH"
    UNCERTAIN = "UNCERTAIN"


class NameComparison(Frozen):
    kind: MatchKind
    reason: str


def compare_name(observed: Extracted[str], person: Person, ctx: EvaluationContext) -> NameComparison:
    anchor = ctx.anchors.for_person(person)
    if not observed.found or not normalize_name(observed.value):
        return NameComparison(kind=MatchKind.UNCERTAIN, reason="name not found by OCR")
    if not observed.is_reliable(ctx.threshold):
        return NameComparison(
            kind=MatchKind.UNCERTAIN,
            reason=f"'{observed.value}' read with low OCR confidence ({observed.confidence:.2f})",
        )
    if anchor.name is None:
        return NameComparison(kind=MatchKind.UNCERTAIN, reason=f"{anchor.describe()}")
    if not anchor.certain:
        return NameComparison(
            kind=MatchKind.UNCERTAIN, reason=f"{anchor.describe()} is uncertain: {anchor.note}"
        )
    if same_name(observed.value, anchor.name):
        return NameComparison(kind=MatchKind.EXACT, reason=f"'{observed.value}' matches {anchor.describe()}")
    kind, why = affidavit_bridge(ctx, person, anchor.name, observed.value)
    if kind is MatchKind.AFFIDAVIT:
        return NameComparison(
            kind=kind, reason=f"'{observed.value}' matches {anchor.describe()} via {why}"
        )
    detail = f" ({why})" if why else ""
    return NameComparison(
        kind=kind, reason=f"'{observed.value}' does not match {anchor.describe()}{detail}"
    )


def affidavit_bridge(
    ctx: EvaluationContext, person: Person, name_a: str, name_b: str
) -> tuple[MatchKind, str]:
    """Rule 5.2: is the a/b spelling difference for `person` covered by a valid affidavit?

    Returns AFFIDAVIT (covered), UNCERTAIN (a covering entry exists but something about it
    could not be read reliably) or MISMATCH (not covered), plus an explanation.
    """
    target = {normalize_name(name_a), normalize_name(name_b)}
    uncertain: list[str] = []
    rejected: list[str] = []
    for aff in ctx.affidavits:
        for entry in aff.entries:
            if entry.person is not person:
                continue
            if not (entry.existing_name.found and entry.different_name.found):
                continue
            pair = {normalize_name(entry.existing_name.value), normalize_name(entry.different_name.value)}
            if pair != target:
                continue
            names_ok = entry.existing_name.is_reliable(ctx.threshold) and entry.different_name.is_reliable(
                ctx.threshold
            )
            valid, problem = _affidavit_valid(aff, person, target, ctx)
            if valid is True and names_ok:
                return MatchKind.AFFIDAVIT, f"notarised affidavit [{aff.doc_id}]"
            if valid is False:
                rejected.append(f"affidavit [{aff.doc_id}] rejected: {problem}")
            else:
                uncertain.append(
                    f"affidavit [{aff.doc_id}] unclear: {problem or 'names read with low OCR confidence'}"
                )
    if uncertain:
        return MatchKind.UNCERTAIN, "; ".join(uncertain + rejected)
    if rejected:
        return MatchKind.MISMATCH, "; ".join(rejected)
    return MatchKind.MISMATCH, "no affidavit covers this spelling difference"


def _affidavit_valid(
    aff: Affidavit, person: Person, pair: set[str], ctx: EvaluationContext
) -> tuple[bool | None, str]:
    """(True, '') valid / (False, why) invalid / (None, why) can't tell."""
    unclear: list[str] = []

    if aff.notary is None:
        return False, "not notarised"
    text = ctx.tri_state(aff.notary.notary_text_present)
    stamp = ctx.tri_state(aff.notary.stamp_present)
    if text is False or stamp is False:
        return False, "not notarised (needs Notary Public/Advocate text and a stamp)"
    if text is None or stamp is None:
        unclear.append("notarisation could not be confirmed")

    same = ctx.tri_state(aff.states_same_person)
    if same is False:
        return False, "does not state 'same person'"
    if same is None:
        unclear.append("'same person' statement could not be confirmed")

    if not aff.deponent_name.found:
        unclear.append("deponent name not found")
    elif not aff.deponent_name.is_reliable(ctx.threshold):
        unclear.append("deponent name read with low OCR confidence")
    else:
        deponent = normalize_name(aff.deponent_name.value)
        accepted: set[str] = set()
        for p in {Person.STUDENT, person}:
            anchor = ctx.anchors.for_person(p)
            if anchor.name and anchor.certain:
                accepted.add(normalize_name(anchor.name))
        if person is Person.STUDENT:
            accepted |= pair  # the student may sign with either spelling being declared
        if deponent not in accepted:
            if not ctx.anchors.student.certain:
                unclear.append("StudentRef uncertain, so the deponent can't be checked")
            else:
                return False, f"deponent '{aff.deponent_name.value}' is not the student or the {person.value.lower()}"

    if unclear:
        return None, "; ".join(unclear)
    return True, ""


class IdStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    AMBIGUOUS = "AMBIGUOUS"
    UNCERTAIN = "UNCERTAIN"
    UNKNOWN = "UNKNOWN"


class Identification(Frozen):
    status: IdStatus
    person: Person | None = None
    via: MatchKind | None = None
    reason: str


def identify(
    observed: Extracted[str],
    ctx: EvaluationContext,
    candidates: tuple[Person, ...] = ALL_PEOPLE,
) -> Identification:
    """Which of the student/father/mother does this name belong to?

    Exact matches win over affidavit-bridged ones. More than one match at the same
    level is AMBIGUOUS (FLAG). No match but some uncertainty is UNCERTAIN (FLAG).
    """
    comparisons = {p: compare_name(observed, p, ctx) for p in candidates}
    for level in (MatchKind.EXACT, MatchKind.AFFIDAVIT):
        hits = [p for p, c in comparisons.items() if c.kind is level]
        if len(hits) == 1:
            return Identification(
                status=IdStatus.IDENTIFIED, person=hits[0], via=level, reason=comparisons[hits[0]].reason
            )
        if len(hits) > 1:
            labels = " and ".join(ctx.anchors.for_person(p).describe() for p in hits)
            return Identification(
                status=IdStatus.AMBIGUOUS, reason=f"'{observed.value}' matches more than one person: {labels}"
            )
    unsure = [c.reason for c in comparisons.values() if c.kind is MatchKind.UNCERTAIN]
    if unsure:
        return Identification(status=IdStatus.UNCERTAIN, reason="; ".join(dict.fromkeys(unsure)))
    return Identification(status=IdStatus.UNKNOWN, reason="; ".join(c.reason for c in comparisons.values()))

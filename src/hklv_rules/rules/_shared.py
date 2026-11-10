"""Checks several document types share: notarisation, English translation, recency,
and assigning a document to the student/father/mother by a name on it."""

from __future__ import annotations

import calendar
from datetime import date

from ..context import EvaluationContext
from ..identity import ALL_PEOPLE, IdStatus, MatchKind, compare_name, identify
from ..models import Extracted, Language, NotaryInfo, Outcome, Person, RuleResult
from ..models.common import Frozen
from ._evidence import ev


def subtract_months(d: date, months: int) -> date:
    """Same day `months` earlier, clamped to the month's last day (31 May - 3 = 28 Feb)."""
    total = d.year * 12 + (d.month - 1) - months
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def notary_rule(rule_id: str, doc_id: str, notary: NotaryInfo | None, ctx: EvaluationContext) -> RuleResult:
    """Notary Public/Advocate text AND a stamp: both seen -> PASS, either absent -> FAIL, unreadable -> FLAG."""

    def result(outcome: Outcome, reason: str, evidence=()) -> RuleResult:
        return RuleResult(rule_id=rule_id, outcome=outcome, reason=reason, evidence=evidence)

    if notary is None:
        return result(Outcome.FAIL, "Not notarised: no Notary Public/Advocate text or stamp")
    evidence = (
        ev(doc_id, "notary.notary_text_present", notary.notary_text_present),
        ev(doc_id, "notary.stamp_present", notary.stamp_present),
    )
    text = ctx.tri_state(notary.notary_text_present)
    stamp = ctx.tri_state(notary.stamp_present)
    missing = [label for label, v in (("Notary Public/Advocate text", text), ("stamp", stamp)) if v is False]
    if missing:
        return result(Outcome.FAIL, f"Not notarised: missing {' and '.join(missing)}", evidence)
    if text is None or stamp is None:
        return result(Outcome.FLAG, "Notarisation could not be confirmed (low OCR confidence)", evidence)
    return result(Outcome.PASS, "Notary Public/Advocate text and stamp present", evidence)


def translation_rule(
    rule_id: str,
    doc_id: str,
    language: Extracted[Language],
    has_translation: Extracted[bool],
    ctx: EvaluationContext,
) -> RuleResult:
    """A Bangla (or mixed) document needs an English translation page."""
    evidence = (ev(doc_id, "language", language), ev(doc_id, "has_english_translation", has_translation))

    def result(outcome: Outcome, reason: str) -> RuleResult:
        return RuleResult(rule_id=rule_id, outcome=outcome, reason=reason, evidence=evidence)

    translated = ctx.tri_state(has_translation)
    if translated is True:
        return result(Outcome.PASS, "English translation present")
    lang = language.value if language.is_reliable(ctx.threshold) else None
    if lang is Language.ENGLISH:
        return result(Outcome.PASS, "Document is in English; no translation needed")
    if lang is None:
        return result(Outcome.FLAG, "Document language could not be determined and no English translation was confirmed")
    if translated is False:
        return result(Outcome.FAIL, f"Document is in {lang.value.title()} and has no English translation")
    return result(Outcome.FLAG, f"Document is in {lang.value.title()}; English translation could not be confirmed")


def recency_rule(
    rule_id: str,
    doc_id: str,
    fields: list[tuple[str, Extracted[date]]],
    months: int,
    ctx: EvaluationContext,
    what: str = "Date",
) -> RuleResult:
    """The latest readable date must be within `months` of the evaluation date (inclusive).

    No date -> FLAG. Future date -> FLAG (likely misread). Too old -> FAIL, unless another
    date on the document was unreadable, in which case FLAG.
    """
    found = [(name, f) for name, f in fields if f.found]
    evidence = tuple(ev(doc_id, name, f) for name, f in found)

    def result(outcome: Outcome, reason: str) -> RuleResult:
        return RuleResult(rule_id=rule_id, outcome=outcome, reason=reason, evidence=evidence)

    if not found:
        return result(Outcome.FLAG, f"No {what} found")
    reliable = [f.value for _, f in found if f.is_reliable(ctx.threshold)]
    if not reliable:
        return result(Outcome.FLAG, f"{what} read with low OCR confidence")
    today = ctx.case.evaluation_date
    cutoff = subtract_months(today, months)
    latest = max(reliable)
    if latest > today:
        return result(Outcome.FLAG, f"{what} {latest:%d-%m-%Y} is after the evaluation date {today:%d-%m-%Y}")
    if latest >= cutoff:
        return result(
            Outcome.PASS, f"Dated {latest:%d-%m-%Y}, within {months} months (on or after {cutoff:%d-%m-%Y})"
        )
    if len(reliable) < len(found):
        return result(
            Outcome.FLAG,
            f"Readable date {latest:%d-%m-%Y} is older than {months} months, but another date is unreadable",
        )
    return result(Outcome.FAIL, f"Dated {latest:%d-%m-%Y}, older than {months} months (cutoff {cutoff:%d-%m-%Y})")


class Assignment(Frozen):
    """Which documents of one type belong to whom, plus the rule results that decided it."""

    assigned: dict[Person, tuple[str, ...]]
    # Documents that could not be assigned (FLAG) but may belong to this person:
    # their name was unreadable, or the comparison with this person was uncertain.
    possible: dict[Person, tuple[str, ...]] = {}
    results: tuple[RuleResult, ...]

    def doc_ids_for(self, person: Person) -> tuple[str, ...]:
        return self.assigned.get(person, ())

    def possible_for(self, person: Person) -> tuple[str, ...]:
        return self.possible.get(person, ())


_MATCHES = (MatchKind.EXACT, MatchKind.AFFIDAVIT)


def assign_by_name(
    rule_id: str,
    label: str,
    docs: list[tuple[str, str, Extracted[str]]],
    ctx: EvaluationContext,
    allowed: tuple[Person, ...] = ALL_PEOPLE,
    unknown_reason: str = "belongs to an unknown person",
) -> Assignment:
    """Assign each (doc_id, field_name, name) to one of the `allowed` people by name.

    PASS when it matches exactly one allowed person. FAIL when it matches someone who is
    not allowed (e.g. the student on a parent-only document) or matches nobody. FLAG when
    unreadable or ambiguous. Two documents for the same person FLAG.
    """
    assigned: dict[Person, list[str]] = {p: [] for p in Person}
    possible: dict[Person, list[str]] = {p: [] for p in Person}
    results: list[RuleResult] = []
    outsiders = tuple(p for p in ALL_PEOPLE if p not in allowed)

    for doc_id, field, name in docs:
        evidence = (ev(doc_id, field, name),)
        ident = identify(name, ctx, candidates=allowed)
        outsider = next((p for p in outsiders if compare_name(name, p, ctx).kind in _MATCHES), None)

        if ident.status is IdStatus.IDENTIFIED and outsider is None:
            assigned[ident.person].append(doc_id)
            how = " (spelling difference covered by affidavit)" if ident.via is MatchKind.AFFIDAVIT else ""
            outcome, reason = (
                Outcome.PASS,
                f"{label} {doc_id} assigned to {ident.person.value.title()}{how}: {ident.reason}",
            )
        elif ident.status is IdStatus.IDENTIFIED:
            possible[ident.person].append(doc_id)
            outcome, reason = (
                Outcome.FLAG,
                f"{label} {doc_id} name matches both the {ident.person.value.lower()} and the "
                f"{outsider.value.lower()}; could not be assigned with certainty",
            )
        elif outsider is not None:
            outcome, reason = (
                Outcome.FAIL,
                f"{label} {doc_id} is in the {outsider.value.lower()}'s name, which is not allowed: "
                f"{compare_name(name, outsider, ctx).reason}",
            )
        elif ident.status is IdStatus.UNKNOWN:
            outcome, reason = Outcome.FAIL, f"{label} {doc_id} {unknown_reason}: {ident.reason}"
        else:  # AMBIGUOUS or UNCERTAIN among the allowed people
            for p in allowed:
                if compare_name(name, p, ctx).kind is not MatchKind.MISMATCH:
                    possible[p].append(doc_id)
            outcome, reason = Outcome.FLAG, f"{label} {doc_id} could not be assigned with certainty: {ident.reason}"
        results.append(RuleResult(rule_id=rule_id, outcome=outcome, reason=reason, evidence=evidence))

    for person, doc_ids in assigned.items():
        if len(doc_ids) > 1:
            results.append(
                RuleResult(
                    rule_id=rule_id,
                    outcome=Outcome.FLAG,
                    reason=f"More than one {label} assigned to {person.value.title()}: {', '.join(doc_ids)}",
                )
            )

    return Assignment(
        assigned={p: tuple(ids) for p, ids in assigned.items() if ids},
        possible={p: tuple(ids) for p, ids in possible.items() if ids},
        results=tuple(results),
    )

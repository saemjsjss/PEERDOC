"""Rulebook v2.5 section 4.4: Family Relationship Certificate (FRC-01 .. FRC-05).

Where a document uses a wording the rulebook doesn't list but which clearly means
the same thing (e.g. 'UNION PORISHAD', relation 'HIMSELF'), the rule returns FLAG
for manual review rather than a hard FAIL.
"""

from __future__ import annotations

import re

from ..context import EvaluationContext
from ..identity import MatchKind, compare_name
from ..models import DeathCertificate, FamilyRelationshipCertificate, FrcMember, Outcome, Person, RuleResult, worst
from ._evidence import ev
from ._shared import notary_rule, recency_rule, subtract_months  # noqa: F401 (re-exported)

FRC_01, FRC_02, FRC_03, FRC_04, FRC_05 = "FRC-01", "FRC-02", "FRC-03", "FRC-04", "FRC-05"
ALL_RULES = (FRC_01, FRC_02, FRC_03, FRC_04, FRC_05)

_ISSUERS = ("UNION PARISHAD", "POURASHAVA", "CITY CORPORATION")
_ISSUER_NEAR_MISSES = (
    "UNION PORISHAD",
    "UNION PARISAD",
    "UNION POROSHOD",
    "PAURASHAVA",
    "PAUROSHOVA",
    "POURASAVA",
    "ইউনিয়ন পরিষদ",
    "পৌরসভা",
    "সিটি কর্পোরেশন",
)
# RULES-v7: any word for the applicant themself counts
_SELF_RELATIONS = {"SELF", "HIMSELF", "HERSELF", "MYSELF", "ONESELF", "APPLICANT", "STUDENT", "CANDIDATE"}
_VALIDITY_MONTHS = 3


def check_frc(ctx: EvaluationContext) -> list[RuleResult]:
    frcs = ctx.case.of_kind(FamilyRelationshipCertificate)
    if not frcs:
        return [
            RuleResult(rule_id=r, outcome=Outcome.FAIL, reason="No Family Relationship Certificate found")
            for r in ALL_RULES
        ]
    results: list[RuleResult] = []
    for frc in frcs:
        results += [
            _frc_01_issuer(frc, ctx),
            _frc_02_identity(frc, ctx),
            _frc_03_parents(frc, ctx),
            _frc_04_date(frc, ctx),
            _frc_05_notary(frc, ctx),
        ]
    return results


def _norm_text(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.upper()).split())


_BANGLA_RELATIONS = {
    "পিতা": "FATHER", "বাবা": "FATHER", "মাতা": "MOTHER", "মা": "MOTHER",
    "নিজ": "SELF", "স্বয়ং": "SELF", "আবেদনকারী": "APPLICANT",
}
# 'Father-in-law', 'Step Mother', 'Grand Father' are other people.
_NOT_THE_PARENT = {"IN", "LAW", "STEP", "GRAND"}


def _relation_words(text: str) -> set[str] | None:
    """The relation's words ('Father (Late)' -> {FATHER, LATE}); None if it is in a script
    this can't interpret (an unknown Bangla word), so the caller treats it as unreadable."""
    words = set(re.findall(r"[A-Z]+", text.upper()))
    words |= {v for k, v in _BANGLA_RELATIONS.items() if re.search(rf"(?<!\w){k}(?!\w)", text)}
    if not words and re.search(r"[^\W\d_]", text):
        return None
    return set() if words & _NOT_THE_PARENT else words


# --- FRC-01 Issuer ----------------------------------------------------------------


def _frc_01_issuer(frc: FamilyRelationshipCertificate, ctx: EvaluationContext) -> RuleResult:
    issuer = frc.issuer_text
    evidence = (ev(frc.doc_id, "issuer_text", issuer),)

    def result(outcome: Outcome, reason: str) -> RuleResult:
        return RuleResult(rule_id=FRC_01, outcome=outcome, reason=reason, evidence=evidence)

    # Keyword presence is checked even at low confidence: finding the exact keyword in
    # shaky text is still a finding; NOT finding it in shaky text is only uncertainty.
    text = _norm_text(issuer.value) if issuer.found else ""
    hit = next((k for k in _ISSUERS if k in text), None)
    if hit:
        return result(Outcome.PASS, f"Issued by a {hit.title()}")
    near = next((k for k in _ISSUER_NEAR_MISSES if _norm_text(k) in text), None)
    if near:
        return result(
            Outcome.FLAG,
            f"Issuer reads '{near}', a spelling not listed in the rulebook "
            "(Union Parishad / Pourashava / City Corporation); confirm manually",
        )
    if not issuer.found:
        return result(Outcome.FLAG, "Issuer text not found by OCR")
    if not issuer.is_reliable(ctx.threshold):
        return result(
            Outcome.FLAG, f"Issuer text '{issuer.value}' read with low OCR confidence; issuer keyword not found"
        )
    return result(
        Outcome.FAIL,
        f"Issuer '{issuer.value}' is not a Union Parishad, Pourashava or City Corporation",
    )


# --- FRC-02 Identity (SELF row) -----------------------------------------------


def _frc_02_identity(frc: FamilyRelationshipCertificate, ctx: EvaluationContext) -> RuleResult:
    self_rows, _, unreadable = _rows_with_relation(frc.members, _SELF_RELATIONS, set(), ctx)

    def result(outcome: Outcome, reason: str, rows: list[FrcMember] = ()) -> RuleResult:
        evidence = tuple(ev(frc.doc_id, "members.name", r.name) for r in rows)
        return RuleResult(rule_id=FRC_02, outcome=outcome, reason=reason, evidence=evidence)

    if len(self_rows) > 1:
        return result(Outcome.FLAG, f"{len(self_rows)} rows marked as the applicant (SELF or a synonym)", self_rows)
    if len(self_rows) == 1:
        row = self_rows[0]
        cmp = compare_name(row.name, Person.STUDENT, ctx)
        return result(_outcome_for(cmp.kind), f"SELF row: {cmp.reason}", [row])
    if unreadable:
        return result(Outcome.FLAG, f"{len(unreadable)} relation cell(s) unreadable; SELF row may be among them", unreadable)
    return result(Outcome.FAIL, "No row with relation SELF (or a synonym: HIMSELF, HERSELF, APPLICANT ...)")


# --- FRC-03 Parents -------------------------------------------------------------


def _frc_03_parents(frc: FamilyRelationshipCertificate, ctx: EvaluationContext) -> RuleResult:
    outcomes: list[Outcome] = []
    reasons: list[str] = []
    evidence = []
    for person in (Person.FATHER, Person.MOTHER):
        rows, _, unreadable = _rows_with_relation(frc.members, {person.value}, set(), ctx)
        evidence += [ev(frc.doc_id, "members.name", r.name) for r in rows]
        label = person.value
        if len(rows) > 1:
            outcomes.append(Outcome.FLAG)
            reasons.append(f"{len(rows)} {label} rows")
        elif len(rows) == 1:
            cmp = compare_name(rows[0].name, person, ctx)
            outcomes.append(_outcome_for(cmp.kind))
            reasons.append(f"{label} row: {cmp.reason}")
        elif unreadable:
            outcomes.append(Outcome.FLAG)
            reasons.append(f"no {label} row found, but {len(unreadable)} relation cell(s) unreadable")
        else:
            outcome, reason, more = _deceased_parent(frc, person, ctx)
            outcomes.append(outcome)
            reasons.append(reason)
            evidence += more
    return RuleResult(rule_id=FRC_03, outcome=worst(outcomes), reason="; ".join(reasons), evidence=tuple(evidence))


_NAME_OK = (MatchKind.EXACT, MatchKind.AFFIDAVIT)


def _deceased_parent(frc: FamilyRelationshipCertificate, person: Person, ctx: EvaluationContext):
    """No row for this parent: allowed when the text names them as "Late <name>" and their
    death certificate is in the case (RULES-v2 FRC-03). Either missing -> FAIL."""
    label = person.value
    deaths = [d for d in ctx.case.of_kind(DeathCertificate) if compare_name(d.deceased_name, person, ctx).kind in _NAME_OK]
    late = [(n, compare_name(n, person, ctx)) for n in frc.late_names]
    late = [(n, c) for n, c in late if c.kind is not MatchKind.MISMATCH]
    if not deaths or not late:
        return Outcome.FAIL, f"no {label} row", []
    name, cmp = max(late, key=lambda nc: nc[1].kind in _NAME_OK)
    evidence = [ev(frc.doc_id, "late_names", name), ev(deaths[0].doc_id, "deceased_name", deaths[0].deceased_name)]
    reason = f"no {label} row; named as late ({cmp.reason}) and death certificate {deaths[0].doc_id} is the {label}'s"
    return (Outcome.PASS if cmp.kind in _NAME_OK else Outcome.FLAG), reason, evidence


def _rows_with_relation(
    members: tuple[FrcMember, ...], wanted: set[str], near: set[str], ctx: EvaluationContext
) -> tuple[list[FrcMember], list[FrcMember], list[FrcMember]]:
    matched, near_matched, unreadable = [], [], []
    for m in members:
        if not m.relation.is_reliable(ctx.threshold):
            unreadable.append(m)
            continue
        words = _relation_words(m.relation.value)
        if words is None:
            unreadable.append(m)
        elif words & wanted:
            matched.append(m)
        elif words & near:
            near_matched.append(m)
    return matched, near_matched, unreadable


def _outcome_for(kind: MatchKind) -> Outcome:
    return {
        MatchKind.EXACT: Outcome.PASS,
        MatchKind.AFFIDAVIT: Outcome.PASS,
        MatchKind.UNCERTAIN: Outcome.FLAG,
        MatchKind.MISMATCH: Outcome.FAIL,
    }[kind]


# --- FRC-04 Date ------------------------------------------------------------------


def _frc_04_date(frc: FamilyRelationshipCertificate, ctx: EvaluationContext) -> RuleResult:
    fields = [("issue_date", frc.issue_date), ("registration_date", frc.registration_date)]
    return recency_rule(FRC_04, frc.doc_id, fields, _VALIDITY_MONTHS, ctx, what="Date of Issue or Registration")


# --- FRC-05 Notary ------------------------------------------------------------------


def _frc_05_notary(frc: FamilyRelationshipCertificate, ctx: EvaluationContext) -> RuleResult:
    return notary_rule(FRC_05, frc.doc_id, frc.notary, ctx)

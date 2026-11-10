"""Rulebook v2.5 section 4.4: Family Relationship Certificate (FRC-01 .. FRC-05).

Where a document uses a wording the rulebook doesn't list but which clearly means
the same thing (e.g. 'UNION PORISHAD', relation 'HIMSELF'), the rule returns FLAG
for manual review rather than a hard FAIL.
"""

from __future__ import annotations

import calendar
import re
from datetime import date

from ..context import EvaluationContext
from ..identity import MatchKind, compare_name
from ..models import FamilyRelationshipCertificate, FrcMember, Outcome, Person, RuleResult, worst
from ._evidence import ev

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
_SELF_RELATIONS = {"SELF", "HERSELF", "APPLICANT"}
_SELF_NEAR_MISSES = {"HIMSELF"}
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


def _norm_relation(text: str) -> str:
    return re.sub(r"[^A-Z]", "", text.upper())


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
    self_rows, near_rows, unreadable = _rows_with_relation(frc.members, _SELF_RELATIONS, _SELF_NEAR_MISSES, ctx)

    def result(outcome: Outcome, reason: str, rows: list[FrcMember] = ()) -> RuleResult:
        evidence = tuple(ev(frc.doc_id, "members.name", r.name) for r in rows)
        return RuleResult(rule_id=FRC_02, outcome=outcome, reason=reason, evidence=evidence)

    if len(self_rows) > 1:
        return result(Outcome.FLAG, f"{len(self_rows)} rows marked SELF/HERSELF/APPLICANT", self_rows)
    if len(self_rows) == 1:
        row = self_rows[0]
        cmp = compare_name(row.name, Person.STUDENT, ctx)
        return result(_outcome_for(cmp.kind), f"SELF row: {cmp.reason}", [row])
    if near_rows:
        relation = near_rows[0].relation.value
        return result(
            Outcome.FLAG,
            f"Applicant row uses relation '{relation}', not SELF/HERSELF/APPLICANT as the rulebook lists; confirm manually",
            near_rows,
        )
    if unreadable:
        return result(Outcome.FLAG, f"{len(unreadable)} relation cell(s) unreadable; SELF row may be among them", unreadable)
    return result(Outcome.FAIL, "No row with relation SELF, HERSELF or APPLICANT")


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
            outcomes.append(Outcome.FAIL)
            reasons.append(f"no {label} row")
    return RuleResult(rule_id=FRC_03, outcome=worst(outcomes), reason="; ".join(reasons), evidence=tuple(evidence))


def _rows_with_relation(
    members: tuple[FrcMember, ...], wanted: set[str], near: set[str], ctx: EvaluationContext
) -> tuple[list[FrcMember], list[FrcMember], list[FrcMember]]:
    matched, near_matched, unreadable = [], [], []
    for m in members:
        if not m.relation.is_reliable(ctx.threshold):
            unreadable.append(m)
            continue
        rel = _norm_relation(m.relation.value)
        if rel in wanted:
            matched.append(m)
        elif rel in near:
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


def subtract_months(d: date, months: int) -> date:
    total = d.year * 12 + (d.month - 1) - months
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _frc_04_date(frc: FamilyRelationshipCertificate, ctx: EvaluationContext) -> RuleResult:
    fields = [("issue_date", frc.issue_date), ("registration_date", frc.registration_date)]
    evidence = tuple(ev(frc.doc_id, name, f) for name, f in fields if f.found)

    def result(outcome: Outcome, reason: str) -> RuleResult:
        return RuleResult(rule_id=FRC_04, outcome=outcome, reason=reason, evidence=evidence)

    found = [f for _, f in fields if f.found]
    if not found:
        return result(Outcome.FLAG, "No Date of Issue or Registration found")
    reliable = [f.value for f in found if f.is_reliable(ctx.threshold)]
    unreliable = len(found) - len(reliable)

    today = ctx.case.evaluation_date
    cutoff = subtract_months(today, _VALIDITY_MONTHS)
    if not reliable:
        return result(Outcome.FLAG, "Date of Issue/Registration read with low OCR confidence")
    latest = max(reliable)
    if latest > today:
        return result(Outcome.FLAG, f"Date {latest:%d-%m-%Y} is after the evaluation date {today:%d-%m-%Y}")
    if latest >= cutoff:
        return result(Outcome.PASS, f"Dated {latest:%d-%m-%Y}, within 3 months (on or after {cutoff:%d-%m-%Y})")
    if unreliable:
        return result(
            Outcome.FLAG,
            f"Readable date {latest:%d-%m-%Y} is older than 3 months, but another date is unreadable",
        )
    return result(Outcome.FAIL, f"Dated {latest:%d-%m-%Y}, older than 3 months (cutoff {cutoff:%d-%m-%Y})")


# --- FRC-05 Notary ------------------------------------------------------------------


def _frc_05_notary(frc: FamilyRelationshipCertificate, ctx: EvaluationContext) -> RuleResult:
    def result(outcome: Outcome, reason: str, evidence=()) -> RuleResult:
        return RuleResult(rule_id=FRC_05, outcome=outcome, reason=reason, evidence=evidence)

    if frc.notary is None:
        return result(Outcome.FAIL, "Not notarised: no Notary Public/Advocate text or stamp")
    evidence = (
        ev(frc.doc_id, "notary.notary_text_present", frc.notary.notary_text_present),
        ev(frc.doc_id, "notary.stamp_present", frc.notary.stamp_present),
    )
    text = ctx.tri_state(frc.notary.notary_text_present)
    stamp = ctx.tri_state(frc.notary.stamp_present)
    missing = [label for label, v in (("Notary Public/Advocate text", text), ("stamp", stamp)) if v is False]
    if missing:
        return result(Outcome.FAIL, f"Not notarised: missing {' and '.join(missing)}", evidence)
    if text is None or stamp is None:
        return result(Outcome.FLAG, "Notarisation could not be confirmed (low OCR confidence)", evidence)
    return result(Outcome.PASS, "Notary Public/Advocate text and stamp present", evidence)

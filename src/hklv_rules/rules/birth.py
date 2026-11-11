"""Rulebook v2.5 section 4.3: Birth Certificate (BIRTH-01 .. BIRTH-04).

  * BIRTH-01 (Format): if Bangla, must have an English translation. Missing -> FAIL.
  * BIRTH-02 (Notary): must be notarised. Missing -> FAIL.
  * BIRTH-03 (DOB): must match the Passport DOB, else FAIL. A Bangla certificate with an
    English translation is checked on the birth year only (agreed 2026-11-12).
  * BIRTH-04 (BRN): the Birth Registration Number must start with the birth year. Mismatch -> FLAG.
  * BIRTH-05 (Name): the name must match StudentRef (the passport). Mismatch -> FAIL.
    Birth Certificates are the student's only; a parent's certificate FAILs here.

A value OCR could not read reliably is a FLAG, never a FAIL.

One result per rule per Birth Certificate. With no Birth Certificate this returns nothing:
REQ-03 already FAILs the case.
"""

from __future__ import annotations

from datetime import date

from ..context import EvaluationContext
from ..identity import MatchKind, compare_name
from ..models import BirthCertificate, Outcome, Passport, Person, RuleResult
from ._evidence import ev
from ..names import normalize_name
from ._shared import digits, edit_distance, notary_rule, translation_rule

BIRTH_01, BIRTH_02, BIRTH_03, BIRTH_04, BIRTH_05 = "BIRTH-01", "BIRTH-02", "BIRTH-03", "BIRTH-04", "BIRTH-05"
ALL_RULES = (BIRTH_01, BIRTH_02, BIRTH_03, BIRTH_04, BIRTH_05)


def check_birth_certificates(ctx: EvaluationContext) -> list[RuleResult]:
    certs = ctx.case.of_kind(BirthCertificate)
    passports = ctx.case.of_kind(Passport)
    results: list[RuleResult] = []
    for cert in certs:
        results += [
            _birth_01_format(cert, ctx),
            _birth_02_notary(cert, ctx),
            _birth_03_dob(cert, passports, ctx),
            _birth_04_brn(cert, passports, ctx),
            _birth_05_name(cert, ctx),
        ]
    return results


def _label(cert: BirthCertificate) -> str:
    return f"Birth Certificate {cert.doc_id}"


def _named(result: RuleResult, cert: BirthCertificate) -> RuleResult:
    """The shared helpers give generic reasons; prefix the document so the reason stands alone."""
    return result.model_copy(update={"reason": f"{_label(cert)}: {result.reason}"})


# --- BIRTH-01 Format / BIRTH-02 Notary -------------------------------------------------


def _birth_01_format(cert: BirthCertificate, ctx: EvaluationContext) -> RuleResult:
    return _named(translation_rule(BIRTH_01, cert.doc_id, cert.language, cert.has_english_translation, ctx), cert)


def _birth_02_notary(cert: BirthCertificate, ctx: EvaluationContext) -> RuleResult:
    return _named(notary_rule(BIRTH_02, cert.doc_id, cert.notary, ctx), cert)


# --- Passport DOB ----------------------------------------------------------------------


def _passport_dobs(passports: list[Passport], ctx: EvaluationContext) -> tuple[list[tuple[str, date]], list[str]]:
    """(doc_id, dob) for every passport whose DOB is reliable, and the ids of passports whose
    DOB was found but read with low confidence."""
    reliable = [(p.doc_id, p.date_of_birth.value) for p in passports if p.date_of_birth.is_reliable(ctx.threshold)]
    shaky = [p.doc_id for p in passports if p.date_of_birth.found and not p.date_of_birth.is_reliable(ctx.threshold)]
    return reliable, shaky


def _no_passport_dob_reason(passports: list[Passport], shaky: list[str]) -> str:
    if not passports:
        return "no Passport in the case"
    if shaky:
        return f"Passport date of birth read with low OCR confidence ({', '.join(shaky)})"
    return f"no date of birth found on the Passport ({', '.join(p.doc_id for p in passports)})"


def _list_dobs(dobs: list[tuple[str, date]]) -> str:
    return ", ".join(f"Passport {doc_id} {d:%d-%m-%Y}" for doc_id, d in dobs)


# --- BIRTH-03 DOB --------------------------------------------------------------------


def _birth_03_dob(cert: BirthCertificate, passports: list[Passport], ctx: EvaluationContext) -> RuleResult:
    label = _label(cert)
    birth_dob = cert.date_of_birth
    passport_dobs, shaky = _passport_dobs(passports, ctx)
    evidence = (ev(cert.doc_id, "date_of_birth", birth_dob),) + tuple(
        ev(p.doc_id, "date_of_birth", p.date_of_birth) for p in passports if p.date_of_birth.found
    )

    def result(outcome: Outcome, reason: str) -> RuleResult:
        return RuleResult(rule_id=BIRTH_03, outcome=outcome, reason=f"{label}: {reason}", evidence=evidence)

    if not birth_dob.found:
        return result(Outcome.FLAG, "no date of birth found, so it can't be compared with the Passport")
    shaky_read = not birth_dob.is_reliable(ctx.threshold)
    if shaky_read and not passport_dobs:
        return result(Outcome.FLAG, "date of birth read with low OCR confidence")
    if not passport_dobs:
        return result(Outcome.FLAG, f"date of birth can't be compared: {_no_passport_dob_reason(passports, shaky)}")
    distinct = {d for _, d in passport_dobs}
    if len(distinct) > 1:
        return result(Outcome.FLAG, f"the Passports disagree on the date of birth ({_list_dobs(passport_dobs)})")

    mine = birth_dob.value
    theirs = distinct.pop()
    passport_ids = ", ".join(doc_id for doc_id, _ in passport_dobs)
    detail = f"date of birth {mine:%d-%m-%Y} vs Passport {passport_ids} {theirs:%d-%m-%Y}"
    year_only = ctx.tri_state(cert.has_english_translation) is True
    if shaky_read:
        # A misread can't land exactly on the passport's date, so agreement is a PASS;
        # disagreement may be the misread, so it stays a FLAG.
        agrees = mine.year == theirs.year if year_only else mine == theirs
        if agrees:
            return result(Outcome.PASS, f"date of birth read with low OCR confidence but agrees with the Passport: {detail}")
        return result(Outcome.FLAG, f"date of birth read with low OCR confidence and differs from the Passport: {detail}")
    if mine == theirs:
        return result(Outcome.PASS, f"date of birth {mine:%d-%m-%Y} matches Passport {passport_ids}")
    if mine.year != theirs.year:
        return result(Outcome.FAIL, f"birth year differs: {detail}")
    if year_only:
        # Translated Bangla certificates are checked on the year only.
        return result(Outcome.PASS, f"birth year {mine.year} matches (translated certificate: year only): {detail}")
    return result(Outcome.FAIL, f"day/month differs: {detail}")


# --- BIRTH-04 BRN ------------------------------------------------------------------------


def _birth_04_brn(cert: BirthCertificate, passports: list[Passport], ctx: EvaluationContext) -> RuleResult:
    label = _label(cert)
    brn = cert.registration_number
    evidence = [ev(cert.doc_id, "registration_number", brn)]

    def result(outcome: Outcome, reason: str) -> RuleResult:
        return RuleResult(rule_id=BIRTH_04, outcome=outcome, reason=f"{label}: {reason}", evidence=tuple(evidence))

    number = digits(brn.value) if brn.found else ""
    if not number:
        return result(Outcome.FLAG, "no Birth Registration Number found")
    if not brn.is_reliable(ctx.threshold):
        return result(Outcome.FLAG, f"Birth Registration Number {number} read with low OCR confidence")

    # Birth year: this certificate's own DOB first, else the Passport's.
    if cert.date_of_birth.is_reliable(ctx.threshold):
        year = cert.date_of_birth.value.year
        evidence.append(ev(cert.doc_id, "date_of_birth", cert.date_of_birth))
        source = "its date of birth"
    else:
        passport_dobs, shaky = _passport_dobs(passports, ctx)
        evidence += [ev(p.doc_id, "date_of_birth", p.date_of_birth) for p in passports if p.date_of_birth.found]
        own = "not found" if not cert.date_of_birth.found else "read with low OCR confidence"
        if not passport_dobs:
            return result(
                Outcome.FLAG,
                f"birth year unknown (date of birth {own}; {_no_passport_dob_reason(passports, shaky)}), "
                f"so BRN {number} can't be checked",
            )
        years = {d.year for _, d in passport_dobs}
        if len(years) > 1:
            return result(
                Outcome.FLAG,
                f"birth year unknown (date of birth {own}; the Passports disagree: {_list_dobs(passport_dobs)}), "
                f"so BRN {number} can't be checked",
            )
        year = years.pop()
        source = f"Passport {', '.join(doc_id for doc_id, _ in passport_dobs)} date of birth (own date of birth {own})"

    if number.startswith(str(year)):
        return result(Outcome.PASS, f"BRN {number} starts with birth year {year} (from {source})")
    return result(
        Outcome.FLAG,
        f"BRN {number} ({len(number)} digits) does not start with birth year {year} (from {source}); "
        "older 13/16-digit BRN formats or a misread number need manual review",
    )


# --- BIRTH-05 Name -----------------------------------------------------------------------

_NAME_OUTCOME = {
    MatchKind.EXACT: Outcome.PASS,
    MatchKind.AFFIDAVIT: Outcome.PASS,
    MatchKind.UNCERTAIN: Outcome.FLAG,
    MatchKind.MISMATCH: Outcome.FAIL,
}


def _birth_05_name(cert: BirthCertificate, ctx: EvaluationContext) -> RuleResult:
    evidence = (ev(cert.doc_id, "name", cert.name),)
    if ctx.anchors.student.name is None:
        outcome, reason = Outcome.FLAG, f"name can't be checked: {ctx.anchors.student.describe()}"
    else:
        cmp = compare_name(cert.name, Person.STUDENT, ctx)
        outcome, reason = _NAME_OUTCOME[cmp.kind], f"name {cmp.reason}"
        if cmp.kind is MatchKind.MISMATCH and _near_miss(cert.name.value, ctx.anchors.student.name):
            outcome, reason = Outcome.FLAG, f"{reason}; only a letter or two apart, which may be an OCR misread"
    return RuleResult(rule_id=BIRTH_05, outcome=outcome, reason=f"{_label(cert)}: {reason}", evidence=evidence)


def _short_key(name: str) -> str:
    # 'MDKAMAL' (OCR lost the space) vs 'MOHAMMAD KAMAL': compare the titles short.
    key = normalize_name(name)
    for title, short in (("MOHAMMAD", "MD"), ("MOSAMMAT", "MST")):
        if key.startswith(title):
            key = short + key[len(title):]
    return key


def _near_miss(observed: str, reference: str) -> bool:
    """Up to two letters apart: an OCR slip on old or low-resolution certificates, so a
    person looks at it instead of the case FAILing. Further apart is a real mismatch."""
    return edit_distance(_short_key(observed), _short_key(reference)) <= 2

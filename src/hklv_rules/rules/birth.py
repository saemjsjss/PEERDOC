"""Rulebook v2.5 section 4.3: Birth Certificate (BIRTH-01 .. BIRTH-04).

  * BIRTH-01 (Format): if Bangla, must have an English translation. Missing -> FAIL.
  * BIRTH-02 (Notary): must be notarised. Missing -> FAIL.
  * BIRTH-03 (DOB): must match the Passport DOB. Year differs -> FAIL; day/month differs -> FLAG.
  * BIRTH-04 (BRN): the Birth Registration Number must start with the birth year. Mismatch -> FLAG.

One result per rule per Birth Certificate. With no Birth Certificate this returns nothing:
REQ-03 already FAILs the case.
"""

from __future__ import annotations

from datetime import date

from ..context import EvaluationContext
from ..models import BirthCertificate, Outcome, Passport, RuleResult
from ._evidence import ev
from ._shared import digits, notary_rule, translation_rule

BIRTH_01, BIRTH_02, BIRTH_03, BIRTH_04 = "BIRTH-01", "BIRTH-02", "BIRTH-03", "BIRTH-04"
ALL_RULES = (BIRTH_01, BIRTH_02, BIRTH_03, BIRTH_04)


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
    if not birth_dob.is_reliable(ctx.threshold):
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
    if mine == theirs:
        return result(Outcome.PASS, f"date of birth {mine:%d-%m-%Y} matches Passport {passport_ids}")
    if mine.year != theirs.year:
        return result(Outcome.FAIL, f"birth year differs: {detail}")
    return result(Outcome.FLAG, f"same year but day/month differs: {detail}")


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

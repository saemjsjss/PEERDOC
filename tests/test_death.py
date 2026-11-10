"""Death Certificate rules (DEATH-01..04)."""

from datetime import date

from builders import FATHER, LOW, MOTHER, STUDENT, affidavit, by_rule, context, death, employment, notarised, tin, trade

from hklv_rules.models import Language, Outcome, Person
from hklv_rules.rules import check_death_certificates


def run(*docs):
    return check_death_certificates(context(*docs))


def test_valid_father_death_certificate_passes_and_is_assigned():
    check = run(death(FATHER))
    assert check.doc_ids_for(Person.FATHER) == ("death",)
    assert {r.outcome for r in check.results} == {Outcome.PASS}
    assert set(by_rule(check.results)) == {"DEATH-01", "DEATH-02", "DEATH-03", "DEATH-04", "DEATH-05"}


def test_mother_death_certificate_is_assigned_to_mother():
    assert run(death(MOTHER)).doc_ids_for(Person.MOTHER) == ("death",)


def test_no_death_certificate_produces_nothing():
    check = run()
    assert check.results == () and check.assigned == {}


# DEATH-01 assignment


def test_death_certificate_for_stranger_fails():
    [r] = [r for r in run(death("JAHANGIR ALAM")).results if r.rule_id == "DEATH-01"]
    assert r.outcome is Outcome.FAIL
    assert "not the father or mother" in r.reason


def test_death_certificate_in_student_name_fails():
    check = run(death(STUDENT))
    [r] = [r for r in check.results if r.rule_id == "DEATH-01"]
    assert r.outcome is Outcome.FAIL
    assert check.assigned == {}


def test_low_confidence_deceased_name_flags_and_is_unresolved():
    check = run(death(FATHER, confidence=LOW))
    [r] = [r for r in check.results if r.rule_id == "DEATH-01"]
    assert r.outcome is Outcome.FLAG
    assert check.possible_for(Person.FATHER) == ("death",)


def test_short_name_bridged_by_affidavit():
    aff = affidavit((Person.MOTHER, MOTHER, "RINA"))
    assert run(death("RINA"), aff).doc_ids_for(Person.MOTHER) == ("death",)


def test_two_death_certificates_for_same_parent_flag():
    check = run(death(FATHER, doc_id="d1"), death("MOHAMMAD KAMAL UDDIN", doc_id="d2"))
    flags = [r for r in check.results if r.rule_id == "DEATH-01" and r.outcome is Outcome.FLAG]
    assert len(flags) == 1 and "More than one" in flags[0].reason


# DEATH-02 translation, DEATH-03 notary


def test_bangla_without_translation_fails():
    r = by_rule(run(death(translated=False)).results)["DEATH-02"]
    assert r.outcome is Outcome.FAIL


def test_english_certificate_needs_no_translation():
    r = by_rule(run(death(language=Language.ENGLISH, translated=None)).results)["DEATH-02"]
    assert r.outcome is Outcome.PASS


def test_not_notarised_fails():
    assert by_rule(run(death(notary=None)).results)["DEATH-03"].outcome is Outcome.FAIL


def test_unreadable_notary_flags():
    assert by_rule(run(death(notary=notarised(confidence=LOW))).results)["DEATH-03"].outcome is Outcome.FLAG


# DEATH-04 date of death


def test_missing_date_of_death_flags():
    assert by_rule(run(death(date_of_death=None)).results)["DEATH-04"].outcome is Outcome.FLAG


def test_future_date_of_death_flags():
    assert by_rule(run(death(date_of_death=date(2027, 1, 1))).results)["DEATH-04"].outcome is Outcome.FLAG


def test_low_confidence_date_of_death_flags():
    r = by_rule(run(death(date_confidence=LOW)).results)["DEATH-04"]
    assert r.outcome is Outcome.FLAG
    assert "low OCR confidence" in r.reason


def test_stranger_fails_even_when_student_anchor_is_uncertain():
    # An uncertain StudentRef must not soften a name that clearly matches neither parent.
    from builders import EVAL_DATE, birth_certificate, passport
    from hklv_rules.context import EvaluationContext
    from hklv_rules.models import CaseFile

    case = CaseFile(
        case_id="t",
        evaluation_date=EVAL_DATE,
        documents=(passport(mrz_given="TANVIRR"), birth_certificate(), death("ABDUR RAHIM")),
    )
    check = check_death_certificates(EvaluationContext.build(case))
    assert by_rule(check.results)["DEATH-01"].outcome is Outcome.FAIL
    assert check.possible == {}


# DEATH-05 consistency with financial documents


def test_employment_letter_issued_after_death_fails():
    r = by_rule(run(death(FATHER, date_of_death=date(2021, 3, 14)), employment(FATHER)).results)["DEATH-05"]
    assert r.outcome is Outcome.FAIL
    assert "after the father's death" in r.reason


def test_employment_letter_without_readable_dates_flags():
    r = by_rule(run(death(FATHER, date_of_death=None), employment(FATHER)).results)["DEATH-05"]
    assert r.outcome is Outcome.FLAG


def test_trade_license_or_tin_of_deceased_parent_flags():
    for doc in (trade(FATHER), tin(FATHER)):
        assert by_rule(run(death(FATHER), doc).results)["DEATH-05"].outcome is Outcome.FLAG


def test_living_parent_as_sponsor_passes():
    r = by_rule(run(death(FATHER), employment(MOTHER), tin(MOTHER)).results)["DEATH-05"]
    assert r.outcome is Outcome.PASS

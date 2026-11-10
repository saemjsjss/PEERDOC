"""Employment Certificate rules (EMP-01..05) and its place in the financial chain."""

from datetime import date

from builders import FATHER, LOW, MOTHER, STUDENT, affidavit, by_rule, context, employment, notarised, tin, trade

from hklv_rules.models import Language, Outcome, Person, overall
from hklv_rules.rules import check_employment, check_financial_chain


def run(*docs):
    return by_rule(check_employment(context(*docs)))


def chain(*docs):
    return by_rule(check_financial_chain(context(*docs)))


def test_valid_certificate_passes_every_rule():
    r = run(employment())
    assert {k: v.outcome for k, v in r.items()} == {f"EMP-0{i}": Outcome.PASS for i in range(1, 6)}


def test_no_certificate_produces_no_results():
    # Absence is REQ-06's job (Trade License may have been submitted instead).
    assert check_employment(context()) == []


# EMP-01 translation


def test_bangla_without_translation_fails():
    r = run(employment(language=Language.BANGLA, translated=False))["EMP-01"]
    assert r.outcome is Outcome.FAIL


def test_bangla_with_translation_passes():
    assert run(employment(language=Language.BANGLA, translated=True))["EMP-01"].outcome is Outcome.PASS


def test_bangla_with_unknown_translation_flags():
    assert run(employment(language=Language.BANGLA, translated=None))["EMP-01"].outcome is Outcome.FLAG


# EMP-02 notary


def test_missing_stamp_fails():
    assert run(employment(notary=notarised(stamp=False)))["EMP-02"].outcome is Outcome.FAIL


def test_not_notarised_fails():
    assert run(employment(notary=None))["EMP-02"].outcome is Outcome.FAIL


# EMP-03 recency (evaluation 2026-11-10, cutoff 2026-08-10)


def test_issued_exactly_three_months_ago_passes():
    assert run(employment(issue_date=date(2026, 8, 10)))["EMP-03"].outcome is Outcome.PASS


def test_issued_too_long_ago_fails():
    assert run(employment(issue_date=date(2026, 8, 9)))["EMP-03"].outcome is Outcome.FAIL


def test_missing_issue_date_flags():
    assert run(employment(issue_date=None))["EMP-03"].outcome is Outcome.FLAG


# EMP-04 current employment


def test_experience_letter_fails():
    r = run(employment(currently_employed=False))["EMP-04"]
    assert r.outcome is Outcome.FAIL
    assert "current employment" in r.reason


def test_unclear_employment_status_flags():
    assert run(employment(currently_employed=None))["EMP-04"].outcome is Outcome.FLAG


# EMP-05 employee


def test_mother_as_employee_passes():
    assert run(employment(name=MOTHER))["EMP-05"].outcome is Outcome.PASS


def test_student_as_employee_fails():
    r = run(employment(name=STUDENT))["EMP-05"]
    assert r.outcome is Outcome.FAIL
    assert "student" in r.reason


def test_stranger_as_employee_fails():
    assert run(employment(name="JAHANGIR ALAM"))["EMP-05"].outcome is Outcome.FAIL


def test_low_confidence_employee_flags():
    assert run(employment(confidence=LOW))["EMP-05"].outcome is Outcome.FLAG


def test_spelling_difference_bridged_by_affidavit():
    aff = affidavit((Person.FATHER, FATHER, "MD. KAMAL UDDEEN"))
    assert run(employment(name="MD. KAMAL UDDEEN"), aff)["EMP-05"].outcome is Outcome.PASS


# Financial chain with an Employment Certificate instead of a Trade License


def test_chain_tin_father_and_employment_father_passes():
    r = chain(tin(FATHER), employment(FATHER))
    assert overall(r.values()) is Outcome.PASS
    assert "Employment Certificate" in r["CHAIN-02"].reason


def test_chain_tin_father_and_employment_mother_fails():
    r = chain(tin(FATHER), employment(MOTHER))
    assert r["CHAIN-02"].outcome is Outcome.FAIL
    assert "TIN belongs to the Father but Employment Certificate belongs to the Mother" in r["CHAIN-02"].reason
    assert overall(r.values()) is Outcome.FAIL


def test_chain_with_employment_in_student_name_fails_chain_03():
    r = chain(tin(FATHER), employment(STUDENT))
    assert r["CHAIN-03"].outcome is Outcome.FAIL


def test_chain_with_both_trade_and_employment_flags():
    r = chain(tin(FATHER), trade(FATHER), employment(FATHER))
    assert {v.outcome for v in r.values()} == {Outcome.FLAG}


def test_chain_without_any_income_document_fails():
    r = chain(tin(FATHER))
    assert {v.outcome for v in r.values()} == {Outcome.FAIL}
    assert "no Trade License or Employment Certificate" in r["CHAIN-01"].reason


def test_low_confidence_employment_status_flags():
    r = run(employment(currently_employed=True, status_confidence=LOW))["EMP-04"]
    assert r.outcome is Outcome.FLAG


def test_chain_tin_in_student_name_fails_even_when_employee_unreadable():
    r = chain(tin(STUDENT), employment(FATHER, confidence=LOW))
    assert r["CHAIN-01"].outcome is Outcome.FLAG
    assert r["CHAIN-03"].outcome is Outcome.FAIL
    assert r["CHAIN-02"].outcome is Outcome.FAIL


def test_chain_tin_in_student_name_fails_even_with_two_income_documents():
    r = chain(tin(STUDENT), employment(FATHER, doc_id="e1"), employment(MOTHER, doc_id="e2"))
    assert r["CHAIN-03"].outcome is Outcome.FAIL


def test_chain_stranger_tin_fails_chain_02_even_when_employee_unreadable():
    r = chain(tin("JAMAL HOSSAIN"), employment(FATHER, confidence=LOW))
    assert r["CHAIN-02"].outcome is Outcome.FAIL
    assert r["CHAIN-03"].outcome is Outcome.FLAG  # can't rule out the unreadable one


def test_chain_with_two_income_documents_one_in_student_name_still_only_flags():
    # The reviewer may pick the father's one, so the student's one alone settles nothing.
    r = chain(tin(FATHER), employment(FATHER, doc_id="e1"), employment(STUDENT, doc_id="e2"))
    assert {v.outcome for v in r.values()} == {Outcome.FLAG}

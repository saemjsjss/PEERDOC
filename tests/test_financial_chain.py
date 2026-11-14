"""Section 5.1 financial chain (RULES-v9): CHAIN-02 checks that the TIN, the income document
and every Bank Solvency belong to the same parent. Whose each document is (student,
stranger, uncertain) is its own rule's job (TIN-03, TRADE-04, EMP-05, BANK-01), so CHAIN-02
reports only the same-parent question, once."""

from builders import FATHER, LOW, MOTHER, STUDENT, affidavit, bank_solvency, context, employment, tin, trade

from hklv_rules.models import Outcome, Person
from hklv_rules.rules import check_financial_chain


def run(*docs, **kw):
    return [r for r in check_financial_chain(context(*docs, **kw))]


def one(*docs, **kw):
    r = run(*docs, **kw)
    assert len(r) == 1 and r[0].rule_id == "CHAIN-02", r
    return r[0]


def test_all_three_father_passes():
    r = one(tin(FATHER), trade(FATHER), bank_solvency(FATHER))
    assert r.outcome is Outcome.PASS and "father" in r.reason


def test_all_three_mother_passes():
    assert one(tin(MOTHER), trade(MOTHER), bank_solvency(MOTHER)).outcome is Outcome.PASS


def test_tin_father_and_trade_mother_fails():
    """The headline requirement: TIN=Father, Trade=Mother must FAIL."""
    r = one(tin(FATHER), trade(MOTHER), bank_solvency(FATHER))
    assert r.outcome is Outcome.FAIL and "different parents" in r.reason


def test_tin_mother_and_trade_father_fails():
    assert one(tin(MOTHER), trade(FATHER), bank_solvency(MOTHER)).outcome is Outcome.FAIL


def test_bank_of_the_other_parent_fails():
    r = one(tin(FATHER), trade(FATHER), bank_solvency(MOTHER))
    assert r.outcome is Outcome.FAIL and "account holder" in r.reason


def test_one_of_two_solvencies_of_the_other_parent_fails():
    r = one(tin(FATHER), trade(FATHER), bank_solvency(FATHER), bank_solvency(MOTHER, doc_id="solvency-2"))
    assert r.outcome is Outcome.FAIL and "solvency-2" in r.reason


def test_spelling_variant_covered_by_affidavit_counts_for_its_parent():
    aff = affidavit((Person.FATHER, FATHER, "MD. KAMAL UDDEEN"))
    assert one(tin("MD. KAMAL UDDEEN"), trade(FATHER), bank_solvency(FATHER), aff).outcome is Outcome.PASS


def test_cross_parent_fails_even_when_affidavit_exists_for_each_parent():
    aff = affidavit((Person.FATHER, FATHER, "MD. KAMAL UDDEEN"), (Person.MOTHER, MOTHER, "RINA BEGOM"))
    assert one(tin("MD. KAMAL UDDEEN"), trade("RINA BEGOM"), bank_solvency(FATHER), aff).outcome is Outcome.FAIL


# --- a link that is not a parent's: reported once, by its own rule, not by CHAIN-02 ----


def test_tin_in_student_name_gives_no_chain_result():  # TIN-03 FAILs it
    assert run(tin(STUDENT), trade(FATHER), bank_solvency(FATHER)) == []


def test_trade_in_student_name_gives_no_chain_result():  # TRADE-04 FAILs it
    assert run(tin(FATHER), trade(STUDENT), bank_solvency(FATHER)) == []


def test_bank_in_student_name_gives_no_chain_result():  # BANK-01 FAILs it
    assert run(tin(FATHER), trade(FATHER), bank_solvency(STUDENT)) == []


def test_stranger_owner_gives_no_chain_result():  # TRADE-04 FAILs it
    assert run(tin(FATHER), trade("JAHANGIR ALAM"), bank_solvency(FATHER)) == []


def test_low_confidence_name_gives_no_chain_result():  # TIN-03 FLAGs it
    assert run(tin(FATHER, confidence=LOW), trade(FATHER), bank_solvency(FATHER)) == []


def test_missing_link_gives_no_chain_result():  # REQ-05 / REQ-06 / REQ-07 FAIL it
    assert run(trade(FATHER), bank_solvency(FATHER)) == []
    assert run(tin(FATHER), bank_solvency(FATHER)) == []
    assert run(tin(FATHER), trade(FATHER)) == []


def test_unassigned_solvency_is_left_out_of_the_comparison():  # BANK-01 FLAGs it
    r = one(tin(FATHER), trade(FATHER), bank_solvency(FATHER), bank_solvency(MOTHER, confidence=LOW, doc_id="s2"))
    assert r.outcome is Outcome.PASS


# --- several income documents ------------------------------------------------------


def test_employment_certificate_is_the_income_link_too():
    assert one(tin(MOTHER), employment(MOTHER), bank_solvency(MOTHER)).outcome is Outcome.PASS


def test_second_income_document_of_the_other_parent_does_not_flag_when_one_parent_fits():
    # v8 FLAGged "reviewer picks" whenever both were submitted; only the father has a TIN.
    r = one(tin(FATHER), trade(FATHER), employment(MOTHER), bank_solvency(FATHER))
    assert r.outcome is Outcome.PASS


def test_both_parents_fit_and_the_bank_decides():
    r = one(tin(FATHER), tin(MOTHER, doc_id="tin-2"), trade(FATHER), employment(MOTHER), bank_solvency(MOTHER))
    assert r.outcome is Outcome.PASS and "mother" in r.reason


def test_both_parents_fit_and_the_banks_are_split_flags():
    r = one(
        tin(FATHER),
        tin(MOTHER, doc_id="tin-2"),
        trade(FATHER),
        employment(MOTHER),
        bank_solvency(FATHER),
        bank_solvency(MOTHER, doc_id="s2"),
    )
    assert r.outcome is Outcome.FLAG and "reviewer" in r.reason

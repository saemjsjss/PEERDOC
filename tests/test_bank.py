"""Section 4.5 Bank Solvency & Statement (BANK-01..04). All data fictional."""

from datetime import date

from builders import (
    ACCOUNT_NUMBER,
    BANK_DATE,
    FATHER,
    LOW,
    MOTHER,
    STUDENT,
    affidavit,
    bank_solvency,
    bank_statement,
    by_rule,
    context,
    ex,
)

from hklv_rules.models import Extracted, Outcome, Person, overall
from hklv_rules.rules.bank import check_bank


def run(*docs):
    return by_rule(check_bank(context(*docs)))


def outcomes(results):
    return {k: v.outcome for k, v in results.items()}


# --- happy path / presence -----------------------------------------------------------


def test_default_solvency_and_statement_pass_every_rule():
    r = run(bank_solvency(), bank_statement())
    assert outcomes(r) == {f"BANK-0{i}": Outcome.PASS for i in range(1, 5)}
    assert "solvency" in r["BANK-02"].reason and "statement" in r["BANK-02"].reason
    assert "20-10-2026" in r["BANK-03"].reason


def test_mother_as_holder_passes():
    r = run(bank_solvency(holder=MOTHER), bank_statement(holder=MOTHER))
    assert r["BANK-01"].outcome is Outcome.PASS
    assert "Mother" in r["BANK-01"].reason


def test_no_solvency_fails_01_to_03_and_passes_04():
    r = run(bank_statement())
    assert outcomes(r) == {
        "BANK-01": Outcome.FAIL,
        "BANK-02": Outcome.FAIL,
        "BANK-03": Outcome.FAIL,
        "BANK-04": Outcome.PASS,
    }
    assert r["BANK-01"].reason == "No bank solvency letter found"


def test_no_bank_documents_at_all():
    r = run()
    assert r["BANK-01"].outcome is Outcome.FAIL
    assert r["BANK-04"].outcome is Outcome.PASS
    assert "no bank documents" in r["BANK-04"].reason


def test_no_statement_fails_02_and_03_but_still_checks_holder():
    r = run(bank_solvency())
    assert r["BANK-01"].outcome is Outcome.PASS
    for rule in ("BANK-02", "BANK-03"):
        assert r[rule].outcome is Outcome.FAIL
        assert "No bank statement to compare against" in r[rule].reason
    assert r["BANK-04"].outcome is Outcome.PASS


def test_one_result_per_solvency_and_one_bank_04_per_case():
    results = check_bank(context(bank_solvency(doc_id="s1"), bank_solvency(doc_id="s2"), bank_statement()))
    ids = [r.rule_id for r in results]
    assert ids.count("BANK-01") == 2 and ids.count("BANK-02") == 2 and ids.count("BANK-03") == 2
    assert ids.count("BANK-04") == 1


# --- BANK-01 holder ------------------------------------------------------------------


def test_holder_is_student_fails():
    r = run(bank_solvency(holder=STUDENT), bank_statement())["BANK-01"]
    assert r.outcome is Outcome.FAIL
    assert "student" in r.reason
    assert r.evidence[0].doc_id == "solvency" and r.evidence[0].field == "account_holder"


def test_holder_is_stranger_fails():
    r = run(bank_solvency(holder="JAMAL HOSSAIN"), bank_statement())["BANK-01"]
    assert r.outcome is Outcome.FAIL
    assert "is not in the father's or mother's name" in r.reason


def test_holder_low_confidence_flags():
    sol = bank_solvency()
    sol = sol.model_copy(update={"account_holder": ex(FATHER, LOW)})
    assert run(sol, bank_statement())["BANK-01"].outcome is Outcome.FLAG


def test_holder_missing_flags():
    sol = bank_solvency().model_copy(update={"account_holder": Extracted[str]()})
    assert run(sol, bank_statement())["BANK-01"].outcome is Outcome.FLAG


def test_holder_spelling_variant_covered_by_affidavit_passes():
    aff = affidavit((Person.FATHER, FATHER, "KAMAL UDDIN"))
    r = run(bank_solvency(holder="KAMAL UDDIN"), bank_statement(), aff)["BANK-01"]
    assert r.outcome is Outcome.PASS
    assert "affidavit" in r.reason


# --- BANK-02 account number --------------------------------------------------------


def test_account_number_formatting_ignored():
    r = run(bank_solvency(account="0123-456-789"), bank_statement(account="A/C 0123456789"))["BANK-02"]
    assert r.outcome is Outcome.PASS


def test_account_number_mismatch_fails():
    r = run(bank_solvency(), bank_statement(account="9999999999"))["BANK-02"]
    assert r.outcome is Outcome.FAIL
    assert "9999999999" in r.reason and "solvency" in r.reason
    assert {(e.doc_id, e.field) for e in r.evidence} == {
        ("solvency", "account_number"),
        ("statement", "account_number"),
    }


def test_solvency_account_number_missing_flags():
    assert run(bank_solvency(account=None), bank_statement())["BANK-02"].outcome is Outcome.FLAG


def test_solvency_account_number_without_digits_flags():
    assert run(bank_solvency(account="N/A"), bank_statement())["BANK-02"].outcome is Outcome.FLAG


def test_statement_account_number_missing_flags():
    r = run(bank_solvency(), bank_statement(account=None))["BANK-02"]
    assert r.outcome is Outcome.FLAG
    assert "statement" in r.reason


def test_low_confidence_solvency_number_flags_even_if_digits_equal():
    sol = bank_solvency().model_copy(update={"account_number": ex(ACCOUNT_NUMBER, LOW)})
    r = run(sol, bank_statement())["BANK-02"]
    assert r.outcome is Outcome.FLAG
    assert "low OCR confidence" in r.reason


def test_low_confidence_statement_number_flags_even_if_digits_equal():
    st = bank_statement().model_copy(update={"account_number": ex(ACCOUNT_NUMBER, LOW)})
    assert run(bank_solvency(), st)["BANK-02"].outcome is Outcome.FLAG


def test_matches_one_of_several_statements_passes():
    r = run(
        bank_solvency(),
        bank_statement(account="5555555555", doc_id="st-other"),
        bank_statement(doc_id="st-main"),
    )["BANK-02"]
    assert r.outcome is Outcome.PASS
    assert "st-main" in r.reason


def test_no_match_among_readable_statements_with_one_unreadable_flags():
    r = run(
        bank_solvency(),
        bank_statement(account="5555555555", doc_id="st-a"),
        bank_statement(account=None, doc_id="st-b"),
    )["BANK-02"]
    assert r.outcome is Outcome.FLAG
    assert "st-b" in r.reason


# --- BANK-03 date match ---------------------------------------------------------------


def test_dates_one_day_apart_fail():
    r = run(bank_solvency(), bank_statement(statement_date=date(2026, 10, 21)))["BANK-03"]
    assert r.outcome is Outcome.FAIL
    assert "20-10-2026" in r.reason and "21-10-2026" in r.reason


def test_letter_date_missing_flags():
    assert run(bank_solvency(letter_date=None), bank_statement())["BANK-03"].outcome is Outcome.FLAG


def test_statement_date_missing_flags():
    assert run(bank_solvency(), bank_statement(statement_date=None))["BANK-03"].outcome is Outcome.FLAG


def test_low_confidence_letter_date_flags():
    sol = bank_solvency().model_copy(update={"letter_date": ex(BANK_DATE, LOW)})
    assert run(sol, bank_statement())["BANK-03"].outcome is Outcome.FLAG


def test_low_confidence_statement_date_flags():
    st = bank_statement().model_copy(update={"statement_date": ex(BANK_DATE, LOW)})
    r = run(bank_solvency(), st)["BANK-03"]
    assert r.outcome is Outcome.FLAG
    assert "low OCR confidence" in r.reason


def test_date_compared_with_the_statement_whose_account_matched():
    r = run(
        bank_solvency(),
        bank_statement(account="5555555555", statement_date=date(2026, 1, 1), doc_id="st-other"),
        bank_statement(doc_id="st-main"),
    )["BANK-03"]
    assert r.outcome is Outcome.PASS
    assert "st-main" in r.reason


def test_date_mismatch_with_matched_statement_fails_even_if_other_statement_date_equal():
    r = run(
        bank_solvency(),
        bank_statement(account="5555555555", doc_id="st-other"),  # same date, other account
        bank_statement(statement_date=date(2026, 10, 1), doc_id="st-main"),
    )["BANK-03"]
    assert r.outcome is Outcome.FAIL


def test_only_statement_is_used_for_date_even_if_account_differs():
    # BANK-02 fails on the number; BANK-03 still compares with the only statement.
    r = run(bank_solvency(), bank_statement(account="9999999999"))
    assert r["BANK-02"].outcome is Outcome.FAIL
    assert r["BANK-03"].outcome is Outcome.PASS


def test_several_statements_none_matching_account_flags_date():
    r = run(
        bank_solvency(),
        bank_statement(account="5555555555", doc_id="st-a"),
        bank_statement(account="6666666666", doc_id="st-b"),
    )
    assert r["BANK-02"].outcome is Outcome.FAIL
    assert r["BANK-03"].outcome is Outcome.FLAG


def test_low_confidence_number_match_does_not_narrow_pairing_and_does_not_fail():
    # Regression: solvency number 0123456780 read at 0.85 "matched" statement B, whose
    # date differs, and BANK-03 FAILed. The match rests on shaky digits, so it decides
    # nothing; statement A (same date, number differs only in the shaky last digit) pairs.
    sol = bank_solvency().model_copy(update={"account_number": ex("0123456780", 0.85)})
    r = run(
        sol,
        bank_statement(account="0123456789", doc_id="st-a"),
        bank_statement(account="0123456780", statement_date=date(2026, 10, 1), doc_id="st-b"),
    )["BANK-03"]
    assert r.outcome is not Outcome.FAIL
    assert r.outcome is Outcome.PASS
    assert "st-a" in r.reason and "pairing uncertain" in r.reason


def test_low_confidence_number_match_with_no_equal_date_flags():
    sol = bank_solvency().model_copy(update={"account_number": ex("0123456780", 0.85)})
    r = run(
        sol,
        bank_statement(account="0123456789", statement_date=date(2026, 9, 1), doc_id="st-a"),
        bank_statement(account="0123456780", statement_date=date(2026, 10, 1), doc_id="st-b"),
    )["BANK-03"]
    assert r.outcome is Outcome.FLAG
    assert "pairing uncertain: account number read with low OCR confidence" in r.reason
    assert {e.doc_id for e in r.evidence} >= {"st-a", "st-b"}


def test_low_confidence_statement_number_match_does_not_fail():
    # Solvency number reliable; the only "match" is a statement number read at LOW.
    r = run(
        bank_solvency(),
        bank_statement(account="5555555555", doc_id="st-a"),
        bank_statement(account=ACCOUNT_NUMBER, statement_date=date(2026, 10, 1), doc_id="st-b").model_copy(
            update={"account_number": ex(ACCOUNT_NUMBER, LOW)}
        ),
    )["BANK-03"]
    assert r.outcome is Outcome.FLAG
    assert "pairing uncertain" in r.reason


def test_equal_date_on_reliably_different_account_does_not_pass_uncertain_pairing():
    # st-a has the letter date but its number reliably differs from the solvency's: not a pair.
    r = run(
        bank_solvency(),
        bank_statement(account="5555555555", doc_id="st-a"),
        bank_statement(statement_date=date(2026, 10, 1), doc_id="st-b").model_copy(
            update={"account_number": ex(ACCOUNT_NUMBER, LOW)}
        ),
    )["BANK-03"]
    assert r.outcome is Outcome.FLAG


def test_reliable_number_match_still_fails_on_different_date():
    r = run(
        bank_solvency(),
        bank_statement(account="5555555555", doc_id="st-other"),
        bank_statement(statement_date=date(2026, 10, 1), doc_id="st-main"),
    )["BANK-03"]
    assert r.outcome is Outcome.FAIL
    assert "st-main" in r.reason


def test_whole_case_overall():
    assert overall(check_bank(context(bank_solvency(), bank_statement()))) is Outcome.PASS
    assert overall(check_bank(context(bank_solvency(holder=STUDENT), bank_statement()))) is Outcome.FAIL

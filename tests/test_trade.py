"""Section 4.6 Trade License (TRADE-01..04). All data fictional."""

from datetime import date

import pytest
from builders import FATHER, LOW, MOTHER, STUDENT, affidavit, by_rule, context, employment, ex, notarised, trade

from hklv_rules.models import Extracted, Language, Outcome, Person
from hklv_rules.rules.trade import check_trade_licenses, current_fiscal_year, parse_fiscal_year


def run(*docs, **kw):
    return by_rule(check_trade_licenses(context(*docs, **kw)))


def test_default_licence_passes_every_rule():
    r = run(trade(FATHER))
    assert {k: v.outcome for k, v in r.items()} == {f"TRADE-0{i}": Outcome.PASS for i in range(1, 5)}
    for result in r.values():
        assert "trade" in result.reason  # names the document


def test_no_trade_licence_produces_no_results():
    assert check_trade_licenses(context()) == []


def test_employment_certificate_is_ignored():
    assert check_trade_licenses(context(employment())) == []


def test_one_result_per_rule_per_licence():
    results = check_trade_licenses(context(trade(FATHER, doc_id="t1"), trade(MOTHER, doc_id="t2")))
    assert [r.rule_id for r in results].count("TRADE-03") == 2


# --- TRADE-01 translation ---------------------------------------------------------


def test_bangla_without_translation_fails():
    r = run(trade(FATHER, language=Language.BANGLA, translated=False))["TRADE-01"]
    assert r.outcome is Outcome.FAIL
    assert r.reason.startswith("Trade License trade:")


def test_bangla_with_translation_passes():
    assert run(trade(FATHER, language=Language.BANGLA, translated=True))["TRADE-01"].outcome is Outcome.PASS


def test_bangla_with_unknown_translation_flags():
    assert run(trade(FATHER, language=Language.BANGLA))["TRADE-01"].outcome is Outcome.FLAG


def test_language_low_confidence_flags():
    t = trade(FATHER).model_copy(update={"language": ex(Language.ENGLISH, LOW)})
    assert run(t)["TRADE-01"].outcome is Outcome.FLAG


# --- TRADE-02 notary --------------------------------------------------------------


def test_not_notarised_fails():
    assert run(trade(FATHER, notary=None))["TRADE-02"].outcome is Outcome.FAIL


def test_missing_stamp_fails():
    assert run(trade(FATHER, notary=notarised(stamp=False)))["TRADE-02"].outcome is Outcome.FAIL


def test_unreadable_notary_flags():
    assert run(trade(FATHER, notary=notarised(confidence=LOW)))["TRADE-02"].outcome is Outcome.FLAG


# --- TRADE-03 fiscal year (evaluation 10-11-2026 -> FY 2026-2027) ------------------


@pytest.mark.parametrize("text", ["2026-2027", "2026-27", "2026/2027", "FY 2026 - 2027", "2026–2027", "২০২৬-২০২৭"])
def test_current_fiscal_year_spellings_pass(text):
    assert run(trade(FATHER, fiscal_year=text))["TRADE-03"].outcome is Outcome.PASS


def test_older_fiscal_year_fails():
    r = run(trade(FATHER, fiscal_year="2025-2026"))["TRADE-03"]
    assert r.outcome is Outcome.FAIL
    assert "2025-2026" in r.reason and "2026-2027" in r.reason and "10-11-2026" in r.reason
    assert r.evidence[0].field == "fiscal_year"


def test_later_fiscal_year_flags():
    r = run(trade(FATHER, fiscal_year="2027-2028"))["TRADE-03"]
    assert r.outcome is Outcome.FLAG
    assert "later" in r.reason


@pytest.mark.parametrize("text", ["2026-2028", "2026-25", "2026", "renewed", "2025-2026 2026-2027"])
def test_unreadable_fiscal_year_flags(text):
    assert run(trade(FATHER, fiscal_year=text))["TRADE-03"].outcome is Outcome.FLAG


def test_missing_fiscal_year_flags():
    assert run(trade(FATHER, fiscal_year=None))["TRADE-03"].outcome is Outcome.FLAG


def test_low_confidence_fiscal_year_flags():
    t = trade(FATHER).model_copy(update={"fiscal_year": ex("2026-2027", LOW)})
    r = run(t)["TRADE-03"]
    assert r.outcome is Outcome.FLAG
    assert "low OCR confidence" in r.reason


def test_fiscal_year_boundary_30_june_still_previous_year():
    r = run(trade(FATHER, fiscal_year="2026-2027"), evaluation_date=date(2027, 6, 30))
    assert r["TRADE-03"].outcome is Outcome.PASS


def test_fiscal_year_boundary_1_july_starts_new_year():
    r = run(trade(FATHER, fiscal_year="2026-2027"), evaluation_date=date(2027, 7, 1))
    assert r["TRADE-03"].outcome is Outcome.FAIL
    r = run(trade(FATHER, fiscal_year="2027-28"), evaluation_date=date(2027, 7, 1))
    assert r["TRADE-03"].outcome is Outcome.PASS


def test_current_fiscal_year_helper():
    assert current_fiscal_year(date(2026, 11, 10)) == (2026, 2027)
    assert current_fiscal_year(date(2027, 6, 30)) == (2026, 2027)
    assert current_fiscal_year(date(2027, 7, 1)) == (2027, 2028)
    assert current_fiscal_year(date(2027, 1, 1)) == (2026, 2027)


def test_parse_fiscal_year_century_wrap():
    assert parse_fiscal_year("1999-00") == (1999, 2000)
    assert parse_fiscal_year("1999-01") is None


# --- TRADE-04 owner ------------------------------------------------------------------


def test_mother_owner_passes():
    r = run(trade(MOTHER))["TRADE-04"]
    assert r.outcome is Outcome.PASS
    assert "Mother" in r.reason


def test_student_owner_fails():
    r = run(trade(STUDENT))["TRADE-04"]
    assert r.outcome is Outcome.FAIL
    assert "student" in r.reason


def test_stranger_owner_fails():
    r = run(trade("JAMAL HOSSAIN"))["TRADE-04"]
    assert r.outcome is Outcome.FAIL
    assert "is not in the father's or mother's name" in r.reason


def test_low_confidence_owner_flags():
    assert run(trade(FATHER, confidence=LOW))["TRADE-04"].outcome is Outcome.FLAG


def test_missing_owner_flags():
    t = trade(FATHER).model_copy(update={"owner_name": Extracted[str]()})
    assert run(t)["TRADE-04"].outcome is Outcome.FLAG


def test_owner_spelling_variant_with_affidavit_passes():
    aff = affidavit((Person.FATHER, FATHER, "KAMAL UDDIN"))
    assert run(trade("KAMAL UDDIN"), aff)["TRADE-04"].outcome is Outcome.PASS

"""Section 4.7 TIN Certificate (TIN-01..03). All data fictional."""

from builders import (
    FATHER,
    LOW,
    MOTHER,
    STUDENT,
    TIN_NUMBER,
    affidavit,
    by_rule,
    context,
    employment,
    ex,
    notarised,
    tin,
    trade,
)

from hklv_rules.models import Extracted, Outcome, Person
from hklv_rules.rules.tin import check_tin


def run(*docs):
    return by_rule(check_tin(context(*docs)))


def test_default_tin_and_trade_pass_every_rule():
    r = run(tin(FATHER), trade(FATHER))
    assert {k: v.outcome for k, v in r.items()} == {f"TIN-0{i}": Outcome.PASS for i in (1, 2, 3)}
    for result in r.values():
        assert "TIN Certificate tin" in result.reason


def test_no_tin_produces_no_results():
    assert check_tin(context(trade(FATHER))) == []


def test_one_result_per_rule_per_tin():
    results = check_tin(context(tin(FATHER, doc_id="t1"), tin(FATHER, doc_id="t2"), trade(FATHER)))
    assert [r.rule_id for r in results].count("TIN-03") == 2


# --- TIN-01 QR ------------------------------------------------------------------------


def test_qr_not_decoded_flags():
    r = run(tin(FATHER, qr=None), trade(FATHER))["TIN-01"]
    assert r.outcome is Outcome.FLAG
    assert "QR could not be decoded" in r.reason
    assert r.evidence[0].field == "qr_decoded"


# --- TIN-02 number match ------------------------------------------------------------------


def test_qr_not_decoded_flags_number_check():
    r = run(tin(FATHER, qr=None), trade(FATHER))["TIN-02"]
    assert r.outcome is Outcome.FLAG


def test_decoded_but_no_tin_in_qr_flags():
    r = run(tin(FATHER, qr=None, qr_decoded=True), trade(FATHER))
    assert r["TIN-01"].outcome is Outcome.PASS
    assert r["TIN-02"].outcome is Outcome.FLAG
    assert "contains no TIN" in r["TIN-02"].reason


def test_formatting_differences_ignored():
    assert run(tin(FATHER, printed="1234-5678-9012"), trade(FATHER))["TIN-02"].outcome is Outcome.PASS


def test_one_digit_difference_flags():
    r = run(tin(FATHER, qr="123456789013"), trade(FATHER))["TIN-02"]
    assert r.outcome is Outcome.FLAG
    assert "1 digit(s) differ" in r.reason


def test_two_digit_difference_flags():
    assert run(tin(FATHER, qr="123456789099"), trade(FATHER))["TIN-02"].outcome is Outcome.FLAG


def test_three_digit_difference_fails():
    r = run(tin(FATHER, qr="123456789999"), trade(FATHER))["TIN-02"]
    assert r.outcome is Outcome.FAIL
    assert {e.field for e in r.evidence} == {"tin_printed", "tin_from_qr"}


def test_printed_tin_missing_flags():
    assert run(tin(FATHER, printed=None), trade(FATHER))["TIN-02"].outcome is Outcome.FLAG


def test_printed_tin_low_confidence_flags():
    t = tin(FATHER).model_copy(update={"tin_printed": ex(TIN_NUMBER, LOW)})
    r = run(t, trade(FATHER))["TIN-02"]
    assert r.outcome is Outcome.FLAG
    assert "low OCR confidence" in r.reason


def test_qr_tin_is_trusted_at_full_confidence():
    r = run(tin(FATHER), trade(FATHER))["TIN-02"]
    qr_ev = next(e for e in r.evidence if e.field == "tin_from_qr")
    assert qr_ev.value == TIN_NUMBER


# --- TIN-03 name match ---------------------------------------------------------------


def test_taxpayer_matches_trade_owner_with_normalisation():
    assert run(tin("MOHAMMAD KAMAL UDDIN"), trade("Md Kamal Uddin"))["TIN-03"].outcome is Outcome.PASS


def test_taxpayer_differs_from_trade_owner_fails():
    r = run(tin(FATHER), trade(MOTHER))["TIN-03"]
    assert r.outcome is Outcome.FAIL
    assert MOTHER in r.reason and "trade" in r.reason
    assert {(e.doc_id, e.field) for e in r.evidence} == {("tin", "taxpayer_name"), ("trade", "owner_name")}


def test_student_in_both_still_passes_name_match():
    # TIN-03 only checks the two names agree; the student-name ban is CHAIN-03 / TRADE-04.
    assert run(tin(STUDENT), trade(STUDENT))["TIN-03"].outcome is Outcome.PASS


def test_spelling_difference_covered_by_affidavit_passes():
    aff = affidavit((Person.FATHER, FATHER, "KAMAL UDDIN"))
    r = run(tin(FATHER), trade("KAMAL UDDIN"), aff)["TIN-03"]
    assert r.outcome is Outcome.PASS
    assert "affidavit" in r.reason


def test_spelling_difference_with_unnotarised_affidavit_fails():
    aff = affidavit((Person.FATHER, FATHER, "KAMAL UDDIN"), notary=notarised(stamp=False))
    assert run(tin(FATHER), trade("KAMAL UDDIN"), aff)["TIN-03"].outcome is Outcome.FAIL


def test_spelling_difference_with_unreadable_affidavit_notary_flags():
    aff = affidavit((Person.FATHER, FATHER, "KAMAL UDDIN"), notary=notarised(confidence=LOW))
    assert run(tin(FATHER), trade("KAMAL UDDIN"), aff)["TIN-03"].outcome is Outcome.FLAG


def test_taxpayer_low_confidence_flags():
    r = run(tin(FATHER, confidence=LOW), trade(FATHER))["TIN-03"]
    assert r.outcome is Outcome.FLAG
    assert "low OCR confidence" in r.reason


def test_taxpayer_missing_flags():
    t = tin(FATHER).model_copy(update={"taxpayer_name": Extracted[str]()})
    assert run(t, trade(FATHER))["TIN-03"].outcome is Outcome.FLAG


def test_trade_owner_low_confidence_flags():
    assert run(tin(FATHER), trade(FATHER, confidence=LOW))["TIN-03"].outcome is Outcome.FLAG


def test_no_trade_licence_no_employment_flags():
    r = run(tin(FATHER))["TIN-03"]
    assert r.outcome is Outcome.FLAG
    assert "No Trade License to compare with" in r.reason


def test_no_trade_licence_compares_with_employment_certificate():
    r = run(tin(FATHER), employment(FATHER))["TIN-03"]
    assert r.outcome is Outcome.PASS
    assert "Employment Certificate" in r.reason


def test_employment_certificate_mismatch_fails():
    r = run(tin(FATHER), employment(MOTHER))["TIN-03"]
    assert r.outcome is Outcome.FAIL
    assert "Employment Certificate instead" in r.reason


def test_trade_licence_takes_precedence_over_employment():
    r = run(tin(FATHER), trade(FATHER), employment(MOTHER))["TIN-03"]
    assert r.outcome is Outcome.PASS
    assert "Employment" not in r.reason


def test_several_trade_licences_all_matching_pass():
    r = run(tin(FATHER), trade(FATHER, doc_id="t1"), trade("MD KAMAL UDDIN", doc_id="t2"))["TIN-03"]
    assert r.outcome is Outcome.PASS


def test_several_trade_licences_none_matching_fail():
    r = run(tin(FATHER), trade(MOTHER, doc_id="t1"), trade("JAMAL HOSSAIN", doc_id="t2"))["TIN-03"]
    assert r.outcome is Outcome.FAIL


def test_several_trade_licences_one_matching_one_not_flags():
    r = run(tin(FATHER), trade(FATHER, doc_id="t1"), trade(MOTHER, doc_id="t2"))["TIN-03"]
    assert r.outcome is Outcome.FLAG

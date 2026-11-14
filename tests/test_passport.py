"""Section 4.1 Passport rule (PASSPORT-01). All data fictional."""

from datetime import date

from builders import EVAL_DATE, LOW, PASSPORT_EXPIRY, by_rule, context, ex, passport

from hklv_rules.models import Extracted, Outcome
from hklv_rules.rules.passport import PASSPORT_01, check_passport


def run(*docs, **kw):
    return check_passport(context(*docs, with_identity_docs=False, **kw))


def one(*docs, **kw):
    return by_rule(run(*docs, **kw))[PASSPORT_01]


def with_fields(**fields):
    """Default passport with some fields replaced by raw Extracted values."""
    return passport().model_copy(update=fields)


# --- PASS path ----------------------------------------------------------------------


def test_default_passport_passes():
    r = one(passport())
    assert r.outcome is Outcome.PASS
    assert r.reason.startswith("Passport passport: ")
    assert "valid until 01-01-2031" in r.reason
    assert "matches MRZ name" in r.reason


def test_default_identity_docs_pass():
    results = check_passport(context())
    assert [r.outcome for r in results] == [Outcome.PASS]


def test_evidence_lists_every_field_used():
    r = one(passport())
    fields = {e.field: e.value for e in r.evidence}
    assert fields == {
        "date_of_expiry": str(PASSPORT_EXPIRY),
        "printed_date_of_expiry": str(PASSPORT_EXPIRY),
        "given_names": "TANVIR",
        "surname": "AHMED",
        "mrz_given_names": "TANVIR",
        "mrz_surname": "AHMED",
    }
    assert {e.doc_id for e in r.evidence} == {"passport"}


# --- No passport ------------------------------------------------------------------


def test_no_passport_gives_no_passport_result():  # RULES-v9: REQ-01 FAILs it, once
    assert run() == []


# --- Expiry -----------------------------------------------------------------------


def test_expired_yesterday_fails():
    r = one(passport(expiry=date(2026, 11, 9)))
    assert r.outcome is Outcome.FAIL
    assert "expired on 09-11-2026" in r.reason


def test_expiring_today_is_not_expired_but_under_12_months():
    r = one(passport(expiry=EVAL_DATE))
    assert r.outcome is Outcome.FAIL
    assert "expired" not in r.reason
    assert "expires on 10-11-2026, less than 12 months after 10-11-2026" in r.reason


def test_expiring_within_12_months_fails():
    r = one(passport(expiry=date(2027, 6, 3)))
    assert r.outcome is Outcome.FAIL
    assert "Passport passport: expires on 03-06-2027, less than 12 months after 10-11-2026" in r.reason


def test_one_day_short_of_12_months_fails():
    assert one(passport(expiry=date(2027, 11, 9))).outcome is Outcome.FAIL


def test_exactly_12_months_passes():
    r = one(passport(expiry=date(2027, 11, 10)))
    assert r.outcome is Outcome.PASS
    assert "valid until 10-11-2027" in r.reason


def test_12_months_from_leap_day_clamps_to_28_february():
    leap = date(2028, 2, 29)
    assert one(passport(expiry=date(2029, 2, 28)), evaluation_date=leap).outcome is Outcome.PASS
    assert one(passport(expiry=date(2029, 2, 27)), evaluation_date=leap).outcome is Outcome.FAIL


def test_missing_expiry_flags():
    r = one(passport(expiry=None))
    assert r.outcome is Outcome.FLAG
    assert "date of expiry not found" in r.reason


def test_low_confidence_expiry_flags_even_when_far_in_future():
    r = one(passport(date_confidence=LOW))
    assert r.outcome is Outcome.FLAG
    assert "low OCR confidence" in r.reason


def test_low_confidence_expired_date_flags_not_fails():
    r = one(passport(expiry=date(2020, 1, 1), date_confidence=LOW))
    assert r.outcome is Outcome.FLAG


# --- Printed vs MRZ name ----------------------------------------------------------


def test_different_mrz_name_flags():
    r = one(passport(mrz_given="TANVIRUL"))
    assert r.outcome is Outcome.FLAG
    assert "printed name 'TANVIR AHMED' does not match MRZ name 'TANVIRUL AHMED'" in r.reason


def test_swapped_word_order_matches():
    r = one(passport(given="KAMAL", surname="UDDIN", mrz_given="UDDIN", mrz_surname="KAMAL"))
    assert r.outcome is Outcome.PASS


def test_spacing_punctuation_and_mrz_fillers_ignored():
    assert one(passport(given="MD. TANVIR", mrz_given="MD TANVIR")).outcome is Outcome.PASS
    assert one(passport(given="ABU TAHER", surname="KHAN", mrz_given="ABUTAHER")).outcome is Outcome.PASS
    assert one(passport(given="ABU TAHER", mrz_given="ABU<TAHER")).outcome is Outcome.PASS
    assert one(passport(given="tanvir", surname="ahmed")).outcome is Outcome.PASS


def test_name_split_differently_between_given_and_surname_matches():
    r = one(passport(given="TANVIR AHMED", surname="KHAN", mrz_given="TANVIR", mrz_surname="AHMED KHAN"))
    assert r.outcome is Outcome.PASS


def test_extra_word_in_mrz_flags():
    assert one(passport(mrz_given="TANVIR HASAN")).outcome is Outcome.FLAG


def test_single_name_passport_without_given_names_matches():
    p = with_fields(given_names=Extracted[str](), mrz_given_names=Extracted[str]())
    assert one(p).outcome is Outcome.PASS


def test_given_names_on_one_side_only_flags():
    p = with_fields(mrz_given_names=Extracted[str]())
    r = one(p)
    assert r.outcome is Outcome.FLAG
    assert "does not match" in r.reason


def test_missing_mrz_name_flags():
    p = with_fields(mrz_given_names=Extracted[str](), mrz_surname=Extracted[str]())
    r = one(p)
    assert r.outcome is Outcome.FLAG
    assert "MRZ name not found" in r.reason


def test_missing_printed_name_flags():
    p = with_fields(given_names=Extracted[str](), surname=ex("   "))
    r = one(p)
    assert r.outcome is Outcome.FLAG
    assert "printed name not found" in r.reason


def test_low_confidence_mrz_name_flags_even_if_identical():
    r = one(with_fields(mrz_surname=ex("AHMED", LOW)))
    assert r.outcome is Outcome.FLAG
    assert "MRZ name read with low OCR confidence" in r.reason


def test_low_confidence_printed_name_confirmed_by_agreeing_mrz_passes():
    assert one(with_fields(given_names=ex("TANVIR", LOW))).outcome is Outcome.PASS


def test_low_confidence_printed_name_flags_when_mrz_disagrees():
    r = one(with_fields(given_names=ex("TANVIR", LOW), mrz_given_names=ex("TANVIER")))
    assert r.outcome is Outcome.FLAG
    assert "printed name read with low OCR confidence" in r.reason


# --- Combining the two checks -----------------------------------------------------


def test_expired_and_name_mismatch_fails_and_reports_both():
    r = one(passport(expiry=date(2025, 1, 1), mrz_surname="AHMAD"))
    assert r.outcome is Outcome.FAIL
    assert "expired on 01-01-2025" in r.reason
    assert "does not match MRZ name" in r.reason


def test_missing_expiry_and_name_mismatch_flags_and_reports_both():
    r = one(passport(expiry=None, mrz_surname="AHMAD"))
    assert r.outcome is Outcome.FLAG
    assert "date of expiry not found" in r.reason
    assert "does not match MRZ name" in r.reason


def test_valid_expiry_does_not_hide_name_mismatch():
    assert one(passport(mrz_surname="AHMAD")).outcome is Outcome.FLAG


# --- Several passports --------------------------------------------------------------


def test_one_result_per_passport():
    results = run(passport(doc_id="p-old", expiry=date(2024, 5, 1)), passport(doc_id="p-new"))
    assert [r.rule_id for r in results] == [PASSPORT_01, PASSPORT_01]
    outcomes = {r.evidence[0].doc_id: r.outcome for r in results}
    assert outcomes == {"p-old": Outcome.FAIL, "p-new": Outcome.PASS}
    assert results[0].reason.startswith("Passport p-old: expired on 01-05-2024")


# --- Printed expiry vs MRZ expiry ("If MRZ and Print mismatch -> FLAG") --------------


def test_printed_expiry_different_from_mrz_flags():
    r = one(passport(expiry=date(2033, 6, 3), printed_expiry=date(2033, 6, 30)))
    assert r.outcome is Outcome.FLAG
    assert "printed expiry 30-06-2033 does not match MRZ expiry 03-06-2033" in r.reason
    assert "valid until 03-06-2033" in r.reason


def test_printed_expiry_equal_to_mrz_passes():
    r = one(passport(expiry=date(2033, 6, 3), printed_expiry=date(2033, 6, 3)))
    assert r.outcome is Outcome.PASS
    assert "printed expiry matches MRZ expiry 03-06-2033" in r.reason


def test_printed_expiry_missing_passes_on_the_mrz_expiry():
    r = one(passport(printed_expiry=None))
    assert r.outcome is Outcome.PASS
    assert "printed expiry not read" in r.reason


def test_low_confidence_printed_expiry_adds_no_finding():
    r = one(with_fields(printed_date_of_expiry=Extracted(value=date(2033, 6, 30), confidence=LOW, source_page=1)))
    assert r.outcome is Outcome.PASS
    assert "printed expiry not read reliably" in r.reason


def test_mismatch_does_not_hide_an_expired_mrz_date():
    r = one(passport(expiry=date(2026, 1, 1), printed_expiry=date(2036, 1, 1)))
    assert r.outcome is Outcome.FAIL
    assert "expired on 01-01-2026" in r.reason
    assert "does not match MRZ expiry" in r.reason


def test_unreliable_mrz_expiry_is_not_rescued_by_the_print():
    r = one(passport(date_confidence=LOW, printed_expiry=PASSPORT_EXPIRY))
    assert r.outcome is Outcome.FLAG
    assert "printed expiry not compared" in r.reason

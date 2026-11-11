"""IELTS / TOPIK rules (LANG-01, LANG-02). Optional document; all data fictional."""

from datetime import date

import pytest
from builders import (
    EVAL_DATE,
    LOW,
    STUDENT,
    STUDENT_DOB,
    affidavit,
    birth_certificate,
    by_rule,
    context,
    ex,
    passport,
)

from hklv_rules.models import Extracted, LanguageTest, LanguageTestKind, Outcome, Person
from hklv_rules.rules.language import check_language_tests

TEST_DATE = date(2025, 6, 14)
CUTOFF = date(2024, 11, 10)  # EVAL_DATE - 24 months


def language_test(
    kind: LanguageTestKind | None = LanguageTestKind.IELTS,
    name: str | None = STUDENT,
    dob: date | None = STUDENT_DOB,
    test_date: date | None = TEST_DATE,
    name_confidence: float = 0.99,
    dob_confidence: float = 0.99,
    date_confidence: float = 0.99,
    kind_confidence: float = 0.99,
    doc_id: str = "ielts",
) -> LanguageTest:
    """Default: an IELTS TRF for the default student, taken well within 2 years."""
    return LanguageTest(
        doc_id=doc_id,
        test=ex(kind, kind_confidence) if kind is not None else Extracted[LanguageTestKind](),
        candidate_name=ex(name, name_confidence) if name is not None else Extracted[str](),
        date_of_birth=ex(dob, dob_confidence) if dob is not None else Extracted[date](),
        test_date=ex(test_date, date_confidence) if test_date is not None else Extracted[date](),
    )


def run(*docs, **kw):
    return by_rule(check_language_tests(context(*docs, **kw)))


def test_no_language_test_returns_nothing():
    assert check_language_tests(context()) == []


def test_valid_ielts_passes_both_rules():
    rs = run(language_test())
    assert set(rs) == {"LANG-01", "LANG-02"}
    assert {r.outcome for r in rs.values()} == {Outcome.PASS}
    assert rs["LANG-01"].reason.startswith("IELTS ielts: taken 14-06-2025")


def test_topik_label_in_reason():
    rs = run(language_test(kind=LanguageTestKind.TOPIK, doc_id="topik"))
    assert rs["LANG-01"].reason.startswith("TOPIK topik:")
    assert rs["LANG-02"].reason.startswith("TOPIK topik:")


def test_unreadable_kind_uses_generic_label():
    rs = run(language_test(kind_confidence=LOW))
    assert rs["LANG-01"].reason.startswith("IELTS/TOPIK ielts:")
    assert rs["LANG-01"].outcome is Outcome.PASS


def test_one_result_per_rule_per_test():
    results = check_language_tests(context(language_test(doc_id="a"), language_test(doc_id="b")))
    assert [r.rule_id for r in results] == ["LANG-01", "LANG-02", "LANG-01", "LANG-02"]


# --- LANG-01 Expiry ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("taken", "outcome"),
    [
        (CUTOFF, Outcome.PASS),  # exactly 2 years: still valid
        (date(2024, 11, 9), Outcome.FAIL),  # one day older
        (EVAL_DATE, Outcome.PASS),  # taken today
        (date(2026, 11, 11), Outcome.FLAG),  # after evaluation date: misread
        (date(2020, 1, 1), Outcome.FAIL),
    ],
)
def test_lang_01_boundaries(taken, outcome):
    r = run(language_test(test_date=taken))["LANG-01"]
    assert r.outcome is outcome
    assert r.evidence[0].field == "test_date"
    assert r.evidence[0].value == str(taken)


def test_lang_01_expired_reason():
    r = run(language_test(test_date=date(2023, 5, 2)))["LANG-01"]
    assert r.reason == "IELTS ielts: taken 02-05-2023, expired (older than 2 years; cutoff 10-11-2024)"


def test_lang_01_future_reason_mentions_misread():
    r = run(language_test(test_date=date(2027, 1, 1)))["LANG-01"]
    assert "after the evaluation date 10-11-2026" in r.reason


def test_lang_01_missing_date_flags():
    r = run(language_test(test_date=None))["LANG-01"]
    assert r.outcome is Outcome.FLAG
    assert "test date not found" in r.reason


def test_lang_01_low_confidence_flags_even_if_expired():
    r = run(language_test(test_date=date(2019, 1, 1), date_confidence=LOW))["LANG-01"]
    assert r.outcome is Outcome.FLAG
    assert "low OCR confidence" in r.reason


def test_lang_01_leap_day_cutoff_clamps():
    # 29 Feb 2028 - 24 months = 28 Feb 2026 (2026 is not a leap year)
    on = run(language_test(test_date=date(2026, 2, 28)), evaluation_date=date(2028, 2, 29))["LANG-01"]
    before = run(language_test(test_date=date(2026, 2, 27)), evaluation_date=date(2028, 2, 29))["LANG-01"]
    assert on.outcome is Outcome.PASS
    assert before.outcome is Outcome.FAIL


# --- LANG-02 Name / DOB -------------------------------------------------------------


def test_lang_02_pass_reason_lists_name_and_dob():
    r = run(language_test())["LANG-02"]
    assert r.outcome is Outcome.PASS
    assert "name:" in r.reason and "date of birth 15-03-2001 matches the passport" in r.reason
    fields = {(e.doc_id, e.field) for e in r.evidence}
    assert fields == {("ielts", "candidate_name"), ("ielts", "date_of_birth"), ("passport", "date_of_birth")}


def test_lang_02_name_mismatch_fails():
    r = run(language_test(name="FARHANA ISLAM"))["LANG-02"]
    assert r.outcome is Outcome.FAIL
    assert "does not match StudentRef" in r.reason
    assert "matches the passport" in r.reason  # DOB part still reported


def test_lang_02_name_spacing_difference_is_exact():
    assert run(language_test(name="TANVIRAHMED"))["LANG-02"].outcome is Outcome.PASS


def test_lang_02_name_mismatch_covered_by_affidavit_passes():
    aff = affidavit((Person.STUDENT, STUDENT, "TANVIR AHAMED"))
    r = run(language_test(name="TANVIR AHAMED"), aff)["LANG-02"]
    assert r.outcome is Outcome.PASS
    assert "affidavit" in r.reason


def test_lang_02_low_confidence_name_flags():
    r = run(language_test(name_confidence=LOW))["LANG-02"]
    assert r.outcome is Outcome.FLAG
    assert "low OCR confidence" in r.reason


def test_lang_02_missing_name_flags():
    r = run(language_test(name=None))["LANG-02"]
    assert r.outcome is Outcome.FLAG
    assert "name not found" in r.reason


def test_lang_02_dob_mismatch_fails():
    r = run(language_test(dob=date(2001, 3, 16)))["LANG-02"]
    assert r.outcome is Outcome.FAIL
    assert "16-03-2001 does not match the passport date of birth 15-03-2001" in r.reason


def test_lang_02_missing_dob_flags():
    r = run(language_test(dob=None))["LANG-02"]
    assert r.outcome is Outcome.FLAG
    assert "date of birth not found on the test" in r.reason


def test_lang_02_low_confidence_dob_flags():
    r = run(language_test(dob=date(1999, 1, 1), dob_confidence=LOW))["LANG-02"]
    assert r.outcome is Outcome.FLAG


def test_lang_02_no_passport():
    # No passport: no StudentRef and no passport DOB. Both halves are missing reference
    # data, so the rule FLAGs (never FAIL on data that could not be established).
    r = run(language_test(), birth_certificate(), with_identity_docs=False)["LANG-02"]
    assert r.outcome is Outcome.FLAG
    assert "name can't be checked: StudentRef (not established" in r.reason
    assert "can't be checked: no passport" in r.reason


def test_lang_02_student_name_not_established_flags():
    # Passport with no readable name -> StudentRef has no name; a reliable test must FLAG.
    pp = passport(given="", surname="")
    r = run(language_test(), pp, birth_certificate(), with_identity_docs=False)["LANG-02"]
    assert r.outcome is Outcome.FLAG
    assert "name can't be checked: StudentRef (not established" in r.reason
    assert "date of birth" in r.reason and "matches the passport" in r.reason


def test_lang_02_passport_dob_missing_flags():
    r = run(language_test(), passport(dob=None), birth_certificate(), with_identity_docs=False)["LANG-02"]
    assert r.outcome is Outcome.FLAG
    assert "passport date of birth not found" in r.reason


def test_lang_02_passport_dob_unreliable_flags():
    pp = passport(date_confidence=LOW)
    r = run(language_test(), pp, birth_certificate(), with_identity_docs=False)["LANG-02"]
    assert r.outcome is Outcome.FLAG
    assert "passport date of birth read with low OCR confidence" in r.reason


def test_lang_02_passports_disagreeing_on_dob_flag():
    second = passport(dob=date(2001, 5, 1), doc_id="passport-2")
    r = run(language_test(), second)["LANG-02"]
    assert r.outcome is Outcome.FLAG
    assert "passports disagree" in r.reason


def test_lang_02_fail_beats_flag():
    # name mismatch (FAIL) + DOB unreadable (FLAG) -> FAIL, reason lists both parts
    r = run(language_test(name="FARHANA ISLAM", dob=None))["LANG-02"]
    assert r.outcome is Outcome.FAIL
    assert "does not match StudentRef" in r.reason and "date of birth not found" in r.reason


def test_lang_02_name_ok_dob_uncertain_flags():
    r = run(language_test(dob_confidence=LOW))["LANG-02"]
    assert r.outcome is Outcome.FLAG

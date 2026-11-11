"""Birth Certificate rules (BIRTH-01..04). All data fictional."""

from datetime import date

from builders import (
    LOW,
    STUDENT_BRN,
    STUDENT_DOB,
    birth_certificate,
    by_rule,
    context,
    notarised,
    passport,
)

from hklv_rules.models import Language, Outcome
from hklv_rules.rules.birth import ALL_RULES, check_birth_certificates


def run(*docs):
    """Evaluate exactly the given documents (no default passport/birth certificate added)."""
    return check_birth_certificates(context(*docs, with_identity_docs=False))


def rules(*docs):
    return by_rule(run(*docs))


def default_rules(**birth_kwargs):
    return rules(passport(), birth_certificate(**birth_kwargs))


# --- whole module ------------------------------------------------------------------


def test_defaults_pass_every_rule():
    results = check_birth_certificates(context())
    got = by_rule(results)
    assert set(got) == set(ALL_RULES)
    assert {r.outcome for r in results} == {Outcome.PASS}
    for r in results:
        assert "Birth Certificate birth" in r.reason
        assert r.evidence


def test_no_birth_certificate_returns_nothing():
    assert run(passport()) == []


def test_one_result_per_rule_per_certificate():
    results = run(passport(), birth_certificate(doc_id="b1"), birth_certificate(doc_id="b2"))
    assert len(results) == 8
    for doc_id in ("b1", "b2"):
        mine = [r for r in results if f"Birth Certificate {doc_id}:" in r.reason]
        assert sorted(r.rule_id for r in mine) == sorted(ALL_RULES)


# --- BIRTH-01 Format ------------------------------------------------------------------


def test_bangla_without_translation_fails():
    r = default_rules(language=Language.BANGLA, translated=False)["BIRTH-01"]
    assert r.outcome is Outcome.FAIL
    assert "no English translation" in r.reason


def test_bangla_with_translation_passes():
    assert default_rules(language=Language.BANGLA, translated=True)["BIRTH-01"].outcome is Outcome.PASS


def test_bangla_translation_unknown_flags():
    assert default_rules(language=Language.BANGLA, translated=None)["BIRTH-01"].outcome is Outcome.FLAG


def test_english_needs_no_translation():
    r = default_rules(language=Language.ENGLISH, translated=None)["BIRTH-01"]
    assert r.outcome is Outcome.PASS
    assert {e.field for e in r.evidence} == {"language", "has_english_translation"}


# --- BIRTH-02 Notary -------------------------------------------------------------------


def test_not_notarised_fails():
    r = default_rules(notary=None)["BIRTH-02"]
    assert r.outcome is Outcome.FAIL
    assert r.reason.startswith("Birth Certificate birth:")


def test_missing_stamp_fails():
    assert default_rules(notary=notarised(stamp=False))["BIRTH-02"].outcome is Outcome.FAIL


def test_low_confidence_notary_flags():
    assert default_rules(notary=notarised(confidence=LOW))["BIRTH-02"].outcome is Outcome.FLAG


# --- BIRTH-03 DOB -----------------------------------------------------------------------


def test_dob_matches_passport_passes():
    r = default_rules()["BIRTH-03"]
    assert r.outcome is Outcome.PASS
    assert "15-03-2001" in r.reason
    assert {(e.doc_id, e.field) for e in r.evidence} == {("birth", "date_of_birth"), ("passport", "date_of_birth")}


def test_year_differs_fails():
    r = default_rules(dob=date(2002, 3, 15))["BIRTH-03"]
    assert r.outcome is Outcome.FAIL
    assert "15-03-2002" in r.reason and "15-03-2001" in r.reason


def test_year_differs_by_one_day_across_new_year_fails():
    r = rules(passport(dob=date(2001, 1, 1)), birth_certificate(dob=date(2000, 12, 31), brn="2000123"))["BIRTH-03"]
    assert r.outcome is Outcome.FAIL


def test_day_differs_flags():
    r = default_rules(dob=date(2001, 3, 16))["BIRTH-03"]
    assert r.outcome is Outcome.FLAG
    assert "day/month" in r.reason


def test_month_differs_flags():
    assert default_rules(dob=date(2001, 4, 15))["BIRTH-03"].outcome is Outcome.FLAG


def test_day_and_month_swapped_flags():
    # 05-03 vs 03-05: typical day/month swap; same year -> FLAG, not FAIL.
    r = rules(passport(dob=date(2001, 3, 5)), birth_certificate(dob=date(2001, 5, 3)))["BIRTH-03"]
    assert r.outcome is Outcome.FLAG


def test_birth_dob_missing_flags():
    r = default_rules(dob=None)["BIRTH-03"]
    assert r.outcome is Outcome.FLAG
    assert "no date of birth" in r.reason


def test_birth_dob_low_confidence_flags_even_if_equal():
    r = default_rules(field_confidence=LOW)["BIRTH-03"]
    assert r.outcome is Outcome.FLAG
    assert "low OCR confidence" in r.reason


def test_no_passport_flags():
    r = rules(birth_certificate())["BIRTH-03"]
    assert r.outcome is Outcome.FLAG
    assert "no Passport" in r.reason


def test_passport_dob_missing_flags():
    r = rules(passport(dob=None), birth_certificate())["BIRTH-03"]
    assert r.outcome is Outcome.FLAG
    assert "no date of birth found on the Passport" in r.reason


def test_passport_dob_low_confidence_flags():
    r = rules(passport(date_confidence=LOW), birth_certificate())["BIRTH-03"]
    assert r.outcome is Outcome.FLAG
    assert "low OCR confidence" in r.reason


def test_low_confidence_passport_ignored_when_another_is_reliable():
    shaky = passport(doc_id="p-old", dob=date(1999, 1, 1), date_confidence=LOW)
    r = rules(passport(), shaky, birth_certificate())["BIRTH-03"]
    assert r.outcome is Outcome.PASS


def test_passports_agreeing_pass():
    r = rules(passport(doc_id="p1"), passport(doc_id="p2"), birth_certificate())["BIRTH-03"]
    assert r.outcome is Outcome.PASS
    assert "p1, p2" in r.reason


def test_passports_disagreeing_flag_even_if_one_matches():
    other = passport(doc_id="p2", dob=date(2001, 3, 16))
    r = rules(passport(doc_id="p1"), other, birth_certificate())["BIRTH-03"]
    assert r.outcome is Outcome.FLAG
    assert "disagree" in r.reason


# --- BIRTH-04 BRN ---------------------------------------------------------------------------


def test_brn_starting_with_birth_year_passes():
    r = default_rules()["BIRTH-04"]
    assert r.outcome is Outcome.PASS
    assert STUDENT_BRN in r.reason and "2001" in r.reason


def test_brn_with_separators_uses_digits_only():
    assert default_rules(brn="2001-269-1234-567890")["BIRTH-04"].outcome is Outcome.PASS


def test_brn_wrong_year_flags_never_fails():
    r = default_rules(brn="20022691234567890")["BIRTH-04"]
    assert r.outcome is Outcome.FLAG
    assert "does not start with birth year 2001" in r.reason


def test_old_short_brn_flags_for_manual_review():
    r = default_rules(brn="2691234567890")["BIRTH-04"]  # 13-digit older format
    assert r.outcome is Outcome.FLAG
    assert "13 digits" in r.reason and "manual review" in r.reason


def test_brn_missing_flags():
    r = default_rules(brn=None)["BIRTH-04"]
    assert r.outcome is Outcome.FLAG
    assert "no Birth Registration Number" in r.reason


def test_brn_without_digits_flags_as_missing():
    assert default_rules(brn="N/A")["BIRTH-04"].outcome is Outcome.FLAG


def test_brn_low_confidence_flags():
    r = default_rules(field_confidence=LOW)["BIRTH-04"]
    assert r.outcome is Outcome.FLAG
    assert "low OCR confidence" in r.reason


def test_brn_year_from_own_dob_even_if_passport_differs():
    # Own DOB 2002 (BIRTH-03 FAILs), BRN starts 2002 -> BIRTH-04 judged against its own DOB.
    got = rules(passport(), birth_certificate(dob=date(2002, 3, 15), brn="20022691234567890"))
    assert got["BIRTH-04"].outcome is Outcome.PASS
    assert got["BIRTH-03"].outcome is Outcome.FAIL


def test_brn_year_falls_back_to_passport_dob():
    r = rules(passport(), birth_certificate(dob=None))["BIRTH-04"]
    assert r.outcome is Outcome.PASS
    assert "Passport passport" in r.reason
    assert ("passport", "date_of_birth") in {(e.doc_id, e.field) for e in r.evidence}


def test_brn_fallback_to_passport_mismatch_flags():
    r = rules(passport(dob=date(2000, 3, 15)), birth_certificate(dob=None))["BIRTH-04"]
    assert r.outcome is Outcome.FLAG


def test_brn_no_birth_year_anywhere_flags():
    r = rules(birth_certificate(dob=None))["BIRTH-04"]
    assert r.outcome is Outcome.FLAG
    assert "birth year unknown" in r.reason


def test_brn_fallback_passports_disagree_on_year_flags():
    docs = (passport(doc_id="p1"), passport(doc_id="p2", dob=date(2000, 3, 15)), birth_certificate(dob=None))
    r = rules(*docs)["BIRTH-04"]
    assert r.outcome is Outcome.FLAG
    assert "disagree" in r.reason


def test_brn_fallback_passports_same_year_different_day_still_usable():
    docs = (passport(doc_id="p1"), passport(doc_id="p2", dob=date(2001, 6, 1)), birth_certificate(dob=None))
    assert rules(*docs)["BIRTH-04"].outcome is Outcome.PASS


def test_dob_default_constants_consistent():
    assert STUDENT_BRN.startswith(str(STUDENT_DOB.year))

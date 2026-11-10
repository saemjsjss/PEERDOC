"""Section 4.4 Family Relationship Certificate rules."""

from datetime import date

from builders import LOW, MOTHER, STUDENT, affidavit, by_rule, context, frc, member, notarised

from hklv_rules.models import Outcome, Person, overall
from hklv_rules.rules import check_frc
from hklv_rules.rules.frc import subtract_months


def run(*docs, **kw):
    return by_rule(check_frc(context(*docs, **kw)))


def test_valid_frc_passes_every_rule():
    r = run(frc())
    assert {k: v.outcome for k, v in r.items()} == {f"FRC-0{i}": Outcome.PASS for i in range(1, 6)}


def test_no_frc_fails_every_rule():
    r = run()
    assert {v.outcome for v in r.values()} == {Outcome.FAIL}


# FRC-01 issuer


def test_pourashava_and_city_corporation_accepted():
    assert run(frc(issuer="Savar Pourashava"))["FRC-01"].outcome is Outcome.PASS
    assert run(frc(issuer="Dhaka North City Corporation"))["FRC-01"].outcome is Outcome.PASS


def test_unlisted_spelling_of_union_parishad_flags():
    r = run(frc(issuer="ELAHABAD UNION PORISHAD"))["FRC-01"]
    assert r.outcome is Outcome.FLAG
    assert "PORISHAD" in r.reason


def test_unrelated_issuer_fails():
    assert run(frc(issuer="Rahman & Associates Law Chamber"))["FRC-01"].outcome is Outcome.FAIL


# FRC-02 identity


def test_herself_and_applicant_count_as_self():
    for rel in ("HERSELF", "Applicant", "self"):
        members = (member(STUDENT, rel), member("MD KAMAL UDDIN", "FATHER"), member(MOTHER, "MOTHER"))
        assert run(frc(members=members))["FRC-02"].outcome is Outcome.PASS, rel


def test_himself_is_flagged_not_failed():
    members = (member(STUDENT, "HIMSELF"), member("MD KAMAL UDDIN", "FATHER"), member(MOTHER, "MOTHER"))
    assert run(frc(members=members))["FRC-02"].outcome is Outcome.FLAG


def test_missing_self_row_fails():
    members = (member("MD KAMAL UDDIN", "FATHER"), member(MOTHER, "MOTHER"))
    assert run(frc(members=members))["FRC-02"].outcome is Outcome.FAIL


def test_self_row_with_other_name_fails():
    members = (member("SADIA AHMED", "SELF"), member("MD KAMAL UDDIN", "FATHER"), member(MOTHER, "MOTHER"))
    assert run(frc(members=members))["FRC-02"].outcome is Outcome.FAIL


def test_unreadable_relation_cells_flag():
    members = (member(STUDENT, "SELF", confidence=LOW), member("MD KAMAL UDDIN", "FATHER"), member(MOTHER, "MOTHER"))
    assert run(frc(members=members))["FRC-02"].outcome is Outcome.FLAG


# FRC-03 parents


def test_missing_mother_row_fails():
    members = (member(STUDENT, "SELF"), member("MD KAMAL UDDIN", "FATHER"))
    r = run(frc(members=members))["FRC-03"]
    assert r.outcome is Outcome.FAIL
    assert "no MOTHER row" in r.reason


def test_short_mother_name_fails_without_affidavit_and_passes_with_one():
    members = (member(STUDENT, "SELF"), member("MD KAMAL UDDIN", "FATHER"), member("RINA", "MOTHER"))
    assert run(frc(members=members))["FRC-03"].outcome is Outcome.FAIL
    aff = affidavit((Person.MOTHER, MOTHER, "RINA"))
    assert run(frc(members=members), aff)["FRC-03"].outcome is Outcome.PASS


# FRC-04 date (evaluation date 2026-11-10 -> cutoff 2026-08-10)


def test_issued_exactly_three_months_ago_passes():
    assert run(frc(issue_date=date(2026, 8, 10)))["FRC-04"].outcome is Outcome.PASS


def test_issued_one_day_too_early_fails():
    assert run(frc(issue_date=date(2026, 8, 9)))["FRC-04"].outcome is Outcome.FAIL


def test_registration_date_counts_when_no_issue_date():
    assert run(frc(issue_date=None, registration_date=date(2026, 10, 1)))["FRC-04"].outcome is Outcome.PASS


def test_future_date_flags():
    assert run(frc(issue_date=date(2026, 12, 1)))["FRC-04"].outcome is Outcome.FLAG


def test_no_date_flags():
    assert run(frc(issue_date=None))["FRC-04"].outcome is Outcome.FLAG


def test_subtract_months_clamps_month_end():
    assert subtract_months(date(2026, 5, 31), 3) == date(2026, 2, 28)
    assert subtract_months(date(2026, 1, 15), 3) == date(2025, 10, 15)


# FRC-05 notary


def test_missing_stamp_fails():
    r = run(frc(notary=notarised(stamp=False)))["FRC-05"]
    assert r.outcome is Outcome.FAIL
    assert "stamp" in r.reason


def test_not_notarised_at_all_fails():
    assert run(frc(notary=None))["FRC-05"].outcome is Outcome.FAIL


def test_unreadable_notary_flags():
    assert run(frc(notary=notarised(confidence=LOW)))["FRC-05"].outcome is Outcome.FLAG


def test_overall_verdict_follows_fail_over_flag():
    r = run(frc(issuer="ELAHABAD UNION PORISHAD", notary=None))
    assert overall(r.values()) is Outcome.FAIL

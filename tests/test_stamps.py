"""RULES-v5 STAMP-01: notary and translator dates. All data fictional."""

from datetime import date

from builders import context, passport

from hklv_rules.models import Extracted, Outcome
from hklv_rules.rules.stamps import check_stamp_dates

TODAY = date(2026, 6, 30)


def d(value, conf=0.97):
    return Extracted[date](value=value, confidence=conf, source_page=1)


def run(notary=(), translator=()):
    doc = passport().model_copy(update={"doc_id": "doc", "notary_dates": notary, "translation_dates": translator})
    return check_stamp_dates(context(doc, with_identity_docs=False, evaluation_date=TODAY))


def test_recent_notary_and_translation_on_different_days_pass():
    r = run(notary=(d(date(2026, 6, 9)),), translator=(d(date(2026, 6, 10)),))
    assert [x.outcome for x in r] == [Outcome.PASS, Outcome.PASS]
    assert "notary date 09-06-2026" in r[0].reason and "translator date 10-06-2026" in r[1].reason


def test_exactly_three_months_passes_one_day_more_fails():
    assert run(notary=(d(date(2026, 3, 30)),))[0].outcome is Outcome.PASS
    r = run(notary=(d(date(2026, 3, 29)),))[0]
    assert r.outcome is Outcome.FAIL
    assert "older than 3 months" in r.reason


def test_below_85_percent_is_ignored_entirely():
    assert run(notary=(d(date(2020, 1, 1), conf=0.84),), translator=(d(date(2020, 1, 1), conf=0.5),)) == []


def test_85_percent_counts():
    assert run(notary=(d(date(2020, 1, 1), conf=0.85),))[0].outcome is Outcome.FAIL


def test_future_date_is_ignored():
    assert run(notary=(d(date(2026, 7, 9)),)) == []


def test_no_dates_no_results():
    assert run() == []

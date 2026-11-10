"""Section 3 required documents, focused on the two substitutions:
Employment Certificate for Trade License (REQ-06) and Death Certificate for NID (REQ-08/09)."""

import pytest
from builders import FATHER, LOW, MOTHER, by_rule, complete_case_documents, context, death, employment, nid

from hklv_rules.models import (
    BankSolvency,
    BankStatement,
    FamilyRelationshipCertificate,
    NationalId,
    Outcome,
    Photo,
    TinCertificate,
    TradeLicense,
)
from hklv_rules.rules import assign_nids, check_death_certificates, check_required_documents


def run_ctx(ctx):
    return by_rule(check_required_documents(ctx, assign_nids(ctx), check_death_certificates(ctx)))


def run(*docs):
    return run_ctx(context(*docs))


def without(kind, docs):
    return [d for d in docs if not isinstance(d, kind)]


def test_complete_submission_passes_every_requirement():
    r = run(*complete_case_documents())
    assert {k: v.outcome for k, v in r.items()} == {f"REQ-{i:02d}": Outcome.PASS for i in range(1, 11)}


def test_empty_submission_fails_everything_but_optional():
    r = run_ctx(context(with_identity_docs=False))
    assert {k for k, v in r.items() if v.outcome is Outcome.FAIL} == {f"REQ-{i:02d}" for i in range(1, 10)}
    assert r["REQ-10"].outcome is Outcome.PASS


# REQ-06


def test_employment_certificate_replaces_trade_license():
    docs = without(TradeLicense, complete_case_documents()) + [employment()]
    assert run(*docs)["REQ-06"].outcome is Outcome.PASS


def test_neither_trade_license_nor_employment_fails():
    r = run(*without(TradeLicense, complete_case_documents()))["REQ-06"]
    assert r.outcome is Outcome.FAIL


# REQ-08 / REQ-09


def test_father_death_certificate_replaces_father_nid():
    docs = [d for d in complete_case_documents() if getattr(d, "doc_id", "") != "n-father"] + [death(FATHER)]
    r = run(*docs)
    assert r["REQ-08"].outcome is Outcome.PASS
    assert "Death Certificate" in r["REQ-08"].reason


def test_mother_death_certificate_replaces_mother_nid():
    docs = [d for d in complete_case_documents() if getattr(d, "doc_id", "") != "n-mother"] + [death(MOTHER)]
    assert run(*docs)["REQ-09"].outcome is Outcome.PASS


def test_father_death_certificate_does_not_cover_mother():
    docs = without(NationalId, complete_case_documents()) + [death(FATHER)]
    r = run(*docs)
    assert r["REQ-08"].outcome is Outcome.PASS
    assert r["REQ-09"].outcome is Outcome.FAIL


def test_no_father_nid_and_no_death_certificate_fails():
    docs = [d for d in complete_case_documents() if getattr(d, "doc_id", "") != "n-father"]
    r = run(*docs)["REQ-08"]
    assert r.outcome is Outcome.FAIL
    assert "No Father NID and no Father Death Certificate" in r.reason


def test_sibling_nid_does_not_count_as_father_nid():
    docs = [d for d in complete_case_documents() if getattr(d, "doc_id", "") != "n-father"] + [nid("n-x", "SADIA AHMED")]
    assert run(*docs)["REQ-08"].outcome is Outcome.FAIL


def test_unreadable_nid_makes_missing_parent_flag_not_fail():
    docs = [d for d in complete_case_documents() if getattr(d, "doc_id", "") != "n-father"]
    docs.append(nid("n-blurry", FATHER, confidence=LOW))
    assert run(*docs)["REQ-08"].outcome is Outcome.FLAG


def test_unreadable_death_certificate_makes_missing_parent_flag_not_fail():
    docs = [d for d in complete_case_documents() if getattr(d, "doc_id", "") != "n-father"]
    docs.append(death(FATHER, confidence=LOW))
    assert run(*docs)["REQ-08"].outcome is Outcome.FLAG


def test_unresolved_document_that_clearly_is_not_the_mother_does_not_soften_req_09():
    # FatherRef uncertain, so the father's NID can't be assigned (FLAG). It reliably reads a
    # name that mismatches the certain MotherRef, so it can't stand in for the mother's NID.
    from builders import EVAL_DATE, passport
    from hklv_rules.context import EvaluationContext
    from hklv_rules.models import CaseFile

    base = [d for d in complete_case_documents() if getattr(d, "doc_id", "") != "n-mother"]
    case = CaseFile(case_id="t", evaluation_date=EVAL_DATE, documents=(passport(), _blurry_father_birth_certificate(), *base))
    r = run_ctx(EvaluationContext.build(case))
    assert r["REQ-08"].outcome is Outcome.FLAG
    assert r["REQ-09"].outcome is Outcome.FAIL


def _blurry_father_birth_certificate():
    from builders import HIGH, ex

    from hklv_rules.models import BirthCertificate

    return BirthCertificate(doc_id="birth", father_name=ex(FATHER, LOW), mother_name=ex(MOTHER, HIGH))


@pytest.mark.parametrize(
    "rule_id, drop",
    [
        ("REQ-02", Photo),
        ("REQ-04", FamilyRelationshipCertificate),
        ("REQ-05", BankSolvency),
        ("REQ-05", BankStatement),
        ("REQ-07", TinCertificate),
    ],
)
def test_each_missing_document_fails_only_its_own_requirement(rule_id, drop):
    r = run(*without(drop, complete_case_documents()))
    assert {k for k, v in r.items() if v.outcome is not Outcome.PASS} == {rule_id}
    assert r[rule_id].outcome is Outcome.FAIL


def test_missing_passport_or_birth_certificate_fails_its_requirement():
    from builders import birth_certificate, passport

    for kept, rule_id in ((birth_certificate(), "REQ-01"), (passport(), "REQ-03")):
        r = run_ctx(context(kept, *complete_case_documents(), with_identity_docs=False))
        assert r[rule_id].outcome is Outcome.FAIL

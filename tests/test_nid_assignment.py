"""Section 2.2 NID auto-assignment."""

from builders import FATHER, LOW, MOTHER, STUDENT, affidavit, context, notarised, nid, passport, birth_certificate

from hklv_rules.context import EvaluationContext
from hklv_rules.models import CaseFile, Outcome, Person
from hklv_rules.rules import assign_nids
from builders import EVAL_DATE


def test_assigns_each_nid_to_its_owner():
    a = assign_nids(context(nid("n-father", "MOHAMMAD KAMAL UDDIN"), nid("n-mother", MOTHER), nid("n-student", STUDENT)))
    assert a.doc_ids_for(Person.FATHER) == ("n-father",)
    assert a.doc_ids_for(Person.MOTHER) == ("n-mother",)
    assert a.doc_ids_for(Person.STUDENT) == ("n-student",)
    assert {r.outcome for r in a.results} == {Outcome.PASS}


def test_sibling_nid_fails():
    a = assign_nids(context(nid("n-sister", "SADIA AHMED")))
    [r] = a.results
    assert r.outcome is Outcome.FAIL
    assert "unknown person or sibling" in r.reason
    assert a.assigned == {}


def test_short_name_on_nid_fails_without_affidavit():
    # Mirrors the sample set: birth certificate 'RINA BEGUM', mother's NID just 'RINA'.
    [r] = assign_nids(context(nid("n-mother", "RINA"))).results
    assert r.outcome is Outcome.FAIL


def test_short_name_on_nid_passes_with_notarised_affidavit():
    aff = affidavit((Person.MOTHER, MOTHER, "RINA"))
    a = assign_nids(context(nid("n-mother", "RINA"), aff))
    assert a.doc_ids_for(Person.MOTHER) == ("n-mother",)
    [r] = a.results
    assert r.outcome is Outcome.PASS
    assert "affidavit" in r.reason


def test_affidavit_for_wrong_person_does_not_bridge():
    aff = affidavit((Person.FATHER, MOTHER, "RINA"))
    [r] = assign_nids(context(nid("n-mother", "RINA"), aff)).results
    assert r.outcome is Outcome.FAIL


def test_affidavit_without_stamp_does_not_bridge():
    aff = affidavit((Person.MOTHER, MOTHER, "RINA"), notary=notarised(stamp=False))
    [r] = assign_nids(context(nid("n-mother", "RINA"), aff)).results
    assert r.outcome is Outcome.FAIL
    assert "not notarised" in r.reason


def test_affidavit_with_unreadable_stamp_flags():
    aff = affidavit((Person.MOTHER, MOTHER, "RINA"), notary=notarised(confidence=LOW))
    [r] = assign_nids(context(nid("n-mother", "RINA"), aff)).results
    assert r.outcome is Outcome.FLAG


def test_affidavit_sworn_by_stranger_does_not_bridge():
    aff = affidavit((Person.MOTHER, MOTHER, "RINA"), deponent="JAHANGIR ALAM")
    [r] = assign_nids(context(nid("n-mother", "RINA"), aff)).results
    assert r.outcome is Outcome.FAIL
    assert "deponent" in r.reason


def test_low_confidence_cardholder_name_flags():
    [r] = assign_nids(context(nid("n1", FATHER, confidence=LOW))).results
    assert r.outcome is Outcome.FLAG
    assert "low OCR confidence" in r.reason


def test_two_nids_for_the_same_parent_flag():
    a = assign_nids(context(nid("n1", FATHER), nid("n2", "MOHD KAMAL UDDIN")))
    assert a.doc_ids_for(Person.FATHER) == ("n1", "n2")
    assert [r.outcome for r in a.results] == [Outcome.PASS, Outcome.PASS, Outcome.FLAG]


def test_student_nid_flags_when_passport_mrz_disagrees_with_print():
    case = CaseFile(
        case_id="t",
        evaluation_date=EVAL_DATE,
        documents=(passport(mrz_given="TANVEER"), birth_certificate(), nid("n-student", STUDENT)),
    )
    [r] = assign_nids(EvaluationContext.build(case)).results
    assert r.outcome is Outcome.FLAG
    assert "MRZ" in r.reason


def test_father_falls_back_to_passport_when_no_birth_certificate():
    case = CaseFile(
        case_id="t",
        evaluation_date=EVAL_DATE,
        documents=(passport(father="KAMAL UDDIN"), nid("n-father", "KAMAL UDDIN")),
    )
    a = assign_nids(EvaluationContext.build(case))
    assert a.doc_ids_for(Person.FATHER) == ("n-father",)

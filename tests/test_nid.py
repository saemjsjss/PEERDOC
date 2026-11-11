"""Section 4.2 NID rules (NID-01 .. NID-03). All data fictional."""

from builders import FATHER, LOW, MOTHER, STUDENT, by_rule, context, ex, nid, notarised

from hklv_rules.models import Extracted, NidVariant, Outcome, Person
from hklv_rules.rules import Assignment, assign_nids
from hklv_rules.rules.nid import ALL_RULES, NID_01, NID_02, NID_03, check_nids


def run_all(*docs):
    ctx = context(*docs)
    return check_nids(ctx, assign_nids(ctx))


def run(*docs):
    """by_rule over the results; only valid when a single NID is in the case."""
    return by_rule(run_all(*docs))


def for_doc(results, doc_id):
    return by_rule(r for r in results if r.reason.startswith(f"NID {doc_id} "))


def father_nid(**kw):
    return nid("n-father", FATHER, **kw)


# --- PASS path ----------------------------------------------------------------------


def test_default_nid_passes_every_rule_and_names_owner():
    r = run(father_nid())
    assert {k: v.outcome for k, v in r.items()} == {rule: Outcome.PASS for rule in ALL_RULES}
    assert all(v.reason.startswith("NID n-father (Father): ") for v in r.values())


def test_no_nids_returns_nothing():
    assert run_all() == []


def test_mother_and_student_owner_labels():
    results = run_all(nid("n-mother", MOTHER, number="6661234567"), nid("n-student", STUDENT, number="7771234567"))
    assert for_doc(results, "n-mother")[NID_01].reason.startswith("NID n-mother (Mother): ")
    assert for_doc(results, "n-student")[NID_01].reason.startswith("NID n-student (Student): ")


def test_unassigned_nid_still_checked_and_labelled():
    r = run(nid("n-x", "SADIA AHMED"))
    assert set(r) == set(ALL_RULES)
    assert all(v.reason.startswith("NID n-x (unassigned): ") for v in r.values())
    assert r[NID_01].outcome is Outcome.PASS


def test_label_follows_given_assignment_only():
    ctx = context(nid("n-1", FATHER))
    manual = Assignment(assigned={Person.MOTHER: ("n-1",)}, results=())
    results = by_rule(check_nids(ctx, manual))
    assert results[NID_02].reason.startswith("NID n-1 (Mother): ")
    empty = by_rule(check_nids(ctx, Assignment(assigned={}, results=())))
    assert empty[NID_03].reason.startswith("NID n-1 (unassigned): ")


def test_one_result_per_rule_per_nid():
    results = run_all(
        nid("n-father", FATHER, number="4441234567"),
        nid("n-mother", MOTHER, number="6661234567", translated=False),
        nid("n-old", "SADIA AHMED", variant=NidVariant.OLD, number="8881234567"),
    )
    assert len(results) == 9
    assert for_doc(results, "n-father")[NID_01].outcome is Outcome.PASS
    assert for_doc(results, "n-mother")[NID_01].outcome is Outcome.FAIL
    assert for_doc(results, "n-old")[NID_01].outcome is Outcome.PASS


# --- NID-01 Translation -------------------------------------------------------------


def test_no_translation_fails():
    r = run(father_nid(translated=False))[NID_01]
    assert r.outcome is Outcome.FAIL
    assert r.reason == "NID n-father (Father): no English translation page"
    assert r.evidence[0].field == "has_english_translation"
    assert r.evidence[0].value == "False"


def test_unknown_translation_flags():
    r = run(father_nid(translated=None))[NID_01]
    assert r.outcome is Outcome.FLAG


def test_low_confidence_translation_flags():
    doc = father_nid().model_copy(update={"has_english_translation": ex(True, LOW)})
    r = run(doc)[NID_01]
    assert r.outcome is Outcome.FLAG
    assert "low OCR confidence" in r.reason


def test_low_confidence_missing_translation_flags_not_fails():
    doc = father_nid().model_copy(update={"has_english_translation": ex(False, LOW)})
    assert run(doc)[NID_01].outcome is Outcome.FLAG


# --- NID-02 Notary ------------------------------------------------------------------


def test_not_notarised_fails():
    r = run(father_nid(notary=None))[NID_02]
    assert r.outcome is Outcome.FAIL
    assert r.reason.startswith("NID n-father (Father): Not notarised")


def test_missing_stamp_fails():
    r = run(father_nid(notary=notarised(stamp=False)))[NID_02]
    assert r.outcome is Outcome.FAIL
    assert "stamp" in r.reason


def test_missing_notary_text_fails():
    assert run(father_nid(notary=notarised(text=False)))[NID_02].outcome is Outcome.FAIL


def test_low_confidence_notary_flags():
    r = run(father_nid(notary=notarised(confidence=LOW)))[NID_02]
    assert r.outcome is Outcome.FLAG
    assert {e.field for e in r.evidence} == {"notary.notary_text_present", "notary.stamp_present"}


# --- NID-03 Number match ------------------------------------------------------------


def test_numbers_match_passes_with_evidence():
    r = run(father_nid())[NID_03]
    assert r.outcome is Outcome.PASS
    assert {e.field: e.value for e in r.evidence} == {
        "number_on_card": "5551234567",
        "number_on_translation": "5551234567",
    }


def test_formatting_differences_ignored():
    assert run(father_nid(number="555 123 4567", translation_number="555-123-4567"))[NID_03].outcome is Outcome.PASS


def test_one_digit_difference_flags():
    r = run(father_nid(translation_number="5551234568"))[NID_03]
    assert r.outcome is Outcome.FLAG
    assert "1 digit(s) differ" in r.reason


def test_two_digit_difference_flags():
    assert run(father_nid(translation_number="5551234588"))[NID_03].outcome is Outcome.FLAG


def test_dropped_digit_counts_as_one_difference():
    assert run(father_nid(translation_number="555123456"))[NID_03].outcome is Outcome.FLAG


def test_three_digit_difference_fails():
    r = run(father_nid(translation_number="5551234888"))[NID_03]
    assert r.outcome is Outcome.FAIL
    assert r.reason.startswith("NID n-father (Father): NID number: 3 digits differ")


def test_missing_card_number_flags():
    r = run(father_nid(number=None, translation_number="5551234567"))[NID_03]
    assert r.outcome is Outcome.FLAG
    assert "number_on_card" in r.reason


def test_missing_translation_number_flags():
    doc = father_nid().model_copy(update={"number_on_translation": Extracted[str]()})
    r = run(doc)[NID_03]
    assert r.outcome is Outcome.FLAG
    assert "number_on_translation not found" in r.reason


def test_low_confidence_numbers_flag_even_when_equal():
    r = run(father_nid(number_confidence=LOW))[NID_03]
    assert r.outcome is Outcome.FLAG
    assert "low OCR confidence" in r.reason


def test_low_confidence_numbers_flag_even_when_far_apart():
    assert run(father_nid(translation_number="9999999999", number_confidence=LOW))[NID_03].outcome is Outcome.FLAG


def test_no_translation_flags_number_check():
    r = run(father_nid(translated=False))[NID_03]
    assert r.outcome is Outcome.FLAG
    assert "no translation to compare against" in r.reason
    assert r.reason.startswith("NID n-father (Father): ")
    assert {e.field for e in r.evidence} == {"number_on_card", "has_english_translation"}


def test_unknown_translation_still_compares_numbers():
    assert run(father_nid(translated=None))[NID_03].outcome is Outcome.PASS
    assert run(father_nid(translated=None, translation_number="5551234888"))[NID_03].outcome is Outcome.FAIL

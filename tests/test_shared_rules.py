"""Shared rule helpers in hklv_rules.rules._shared. All data fictional."""

from builders import MOTHER, STUDENT, birth_certificate, context, ex, passport

from hklv_rules.models import Extracted, Language, Outcome, Person
from hklv_rules.rules._shared import assign_by_name, digit_difference, number_match_rule, translation_rule

STRANGER = "MD. ABDUL KARIM"


def _ctx_without_father_anchor():
    """Birth Certificate whose father name was not read, and no passport fallback."""
    birth = birth_certificate().model_copy(update={"father_name": Extracted[str]()})
    ctx = context(passport(), birth, with_identity_docs=False)
    assert ctx.anchors.father.name is None
    assert ctx.anchors.mother.name == MOTHER
    return ctx


# --- assign_by_name: unestablished anchor -> FLAG, not FAIL (fix 3) ----------------------


def test_assign_unknown_name_with_unestablished_anchor_flags():
    ctx = _ctx_without_father_anchor()
    a = assign_by_name("X-01", "Document", [("doc", "name", ex(STRANGER))], ctx, allowed=(Person.FATHER, Person.MOTHER))
    (r,) = a.results
    assert r.outcome is Outcome.FLAG
    assert "could not be assigned with certainty" in r.reason
    assert "FatherRef (not established" in r.reason
    assert a.assigned == {}
    assert a.possible_for(Person.FATHER) == ("doc",)
    assert a.possible_for(Person.MOTHER) == ()


def test_assign_name_matching_established_person_still_passes_without_other_anchor():
    ctx = _ctx_without_father_anchor()
    a = assign_by_name("X-01", "Document", [("doc", "name", ex(MOTHER))], ctx, allowed=(Person.FATHER, Person.MOTHER))
    (r,) = a.results
    assert r.outcome is Outcome.PASS
    assert a.doc_ids_for(Person.MOTHER) == ("doc",)


def test_assign_unknown_name_with_all_anchors_established_still_fails():
    ctx = context()
    a = assign_by_name("X-01", "Document", [("doc", "name", ex(STRANGER))], ctx, allowed=(Person.FATHER, Person.MOTHER))
    (r,) = a.results
    assert r.outcome is Outcome.FAIL
    assert "unknown person" in r.reason
    assert a.possible == {}


def test_assign_outsider_still_fails_when_an_allowed_anchor_is_missing():
    # The student's name on a parent-only document stays a FAIL.
    ctx = _ctx_without_father_anchor()
    a = assign_by_name("X-01", "Document", [("doc", "name", ex(STUDENT))], ctx, allowed=(Person.FATHER, Person.MOTHER))
    (r,) = a.results
    assert r.outcome is Outcome.FAIL
    assert "not allowed" in r.reason


# --- translation_rule: MIXED without translation -> FLAG (fix 4) -------------------------


def _translation(language: Language, translated: bool | None):
    has = ex(translated) if translated is not None else Extracted[bool]()
    return translation_rule("X-01", "doc", ex(language), has, context())


def test_translation_bangla_without_translation_fails():
    assert _translation(Language.BANGLA, False).outcome is Outcome.FAIL


def test_translation_mixed_without_translation_flags():
    r = _translation(Language.MIXED, False)
    assert r.outcome is Outcome.FLAG
    assert "partly in Bangla" in r.reason and "confirm the English text is complete" in r.reason


def test_translation_mixed_with_translation_passes():
    assert _translation(Language.MIXED, True).outcome is Outcome.PASS


def test_translation_mixed_translation_unknown_flags():
    assert _translation(Language.MIXED, None).outcome is Outcome.FLAG


def test_translation_english_passes():
    assert _translation(Language.ENGLISH, False).outcome is Outcome.PASS


# --- digit_difference / number_match_rule (fix 6) ----------------------------------------


def test_digit_difference_same_length_counts_positions():
    assert digit_difference("123456789012", "234567890121") == 12
    assert digit_difference("123456789012", "123456789013") == 1
    assert digit_difference("123456789012", "123456789012") == 0
    assert digit_difference("1234-5678", "12345679") == 1  # non-digits ignored


def test_digit_difference_different_length_uses_edit_distance():
    assert digit_difference("123456789012", "12345678901") == 1  # dropped last digit
    assert digit_difference("123456789012", "13456789012") == 1  # dropped a middle digit


def test_number_match_completely_different_same_length_fails():
    ctx = context()
    r = number_match_rule("X-02", "doc", "Number", ("printed", ex("123456789012")), ("qr", ex("234567890121")), ctx)
    assert r.outcome is Outcome.FAIL
    assert "12 digits differ" in r.reason


def test_number_match_two_substitutions_flags():
    ctx = context()
    r = number_match_rule("X-02", "doc", "Number", ("printed", ex("123456789012")), ("qr", ex("923456789013")), ctx)
    assert r.outcome is Outcome.FLAG

"""Section 5.1 financial chain: TIN taxpayer, Trade License owner and (RULES-v6) bank account
holder must be the same parent."""

from builders import FATHER, LOW, MOTHER, STUDENT, affidavit, bank_solvency, by_rule, context, employment, tin, trade

from hklv_rules.models import BankSolvency, Outcome, Person, overall
from hklv_rules.rules import check_financial_chain


def run(*docs, **kw):
    """CHAIN-02/03 only; CHAIN-04 (the bank link) has its own tests below."""
    return by_rule(r for r in check_financial_chain(context(*docs, **kw)) if r.rule_id != "CHAIN-04")


def chain04(*docs, **kw):
    return [r for r in check_financial_chain(context(*docs, **kw)) if r.rule_id == "CHAIN-04"]


def test_tin_father_and_trade_father_passes():
    r = run(tin(FATHER), trade(FATHER))
    assert {k: v.outcome for k, v in r.items()} == {
        "CHAIN-02": Outcome.PASS,
        "CHAIN-03": Outcome.PASS,
    }
    assert "Father" in r["CHAIN-02"].reason


def test_tin_mother_and_trade_mother_passes():
    r = run(tin(MOTHER), trade(MOTHER))
    assert overall(r.values()) is Outcome.PASS


def test_tin_father_and_trade_mother_fails():
    """The headline requirement: TIN=Father, Trade=Mother must FAIL."""
    r = run(tin(FATHER), trade(MOTHER))

    assert r["CHAIN-02"].outcome is Outcome.FAIL
    assert "TIN belongs to the Father but Trade License belongs to the Mother" in r["CHAIN-02"].reason
    assert r["CHAIN-03"].outcome is Outcome.PASS  # neither is the student
    assert overall(r.values()) is Outcome.FAIL


def test_tin_mother_and_trade_father_fails():
    r = run(tin(MOTHER), trade(FATHER))
    assert r["CHAIN-02"].outcome is Outcome.FAIL
    assert overall(r.values()) is Outcome.FAIL


def test_cross_parent_fails_even_when_affidavit_exists_for_each_parent():
    # Affidavits fix spellings of one person; they never merge father and mother.
    aff = affidavit((Person.FATHER, FATHER, "KAMAL UDDIN"), (Person.MOTHER, MOTHER, "RINA"))
    r = run(tin(FATHER), trade(MOTHER), aff)
    assert r["CHAIN-02"].outcome is Outcome.FAIL


def test_trade_license_in_student_name_fails_chain_02_only():
    # The owner being the student is TRADE-04's FAIL; CHAIN-03 checks only the TIN.
    r = run(tin(FATHER), trade(STUDENT))
    assert r["CHAIN-03"].outcome is Outcome.PASS
    assert r["CHAIN-02"].outcome is Outcome.FAIL


def test_tin_in_student_name_fails_chain_03():
    r = run(tin(STUDENT), trade(FATHER))
    assert r["CHAIN-03"].outcome is Outcome.FAIL
    assert "TIN" in r["CHAIN-03"].reason


def test_both_in_student_name_fails_even_though_names_are_identical():
    r = run(tin(STUDENT), trade(STUDENT))
    assert r["CHAIN-02"].outcome is Outcome.FAIL  # identical, but not a parent
    assert r["CHAIN-03"].outcome is Outcome.FAIL
    assert overall(r.values()) is Outcome.FAIL


def test_md_abbreviation_is_identical_to_mohammad():
    r = run(tin("MOHAMMAD KAMAL UDDIN"), trade("MD KAMAL UDDIN"))
    assert overall(r.values()) is Outcome.PASS


def test_spelling_variant_without_affidavit_fails():
    r = run(tin("MD. KAMAL UDDIN"), trade("MD. KAMAL UDDEEN"))
    assert r["CHAIN-02"].outcome is Outcome.FAIL  # trade owner matches no parent


def test_spelling_variant_covered_by_notarised_affidavit_passes():
    aff = affidavit((Person.FATHER, FATHER, "MD. KAMAL UDDEEN"))
    r = run(tin(FATHER), trade("MD. KAMAL UDDEEN"), aff)
    assert {v.outcome for v in r.values()} == {Outcome.PASS}


def test_owner_who_is_not_a_family_member_fails():
    r = run(tin("JAHANGIR ALAM"), trade("JAHANGIR ALAM"))
    assert r["CHAIN-02"].outcome is Outcome.FAIL
    assert "matches no parent" in r["CHAIN-02"].reason


def test_low_confidence_name_flags_instead_of_guessing():
    r = run(tin(FATHER, confidence=LOW), trade(FATHER))
    assert {v.outcome for v in r.values()} == {Outcome.FLAG}
    assert "low OCR confidence" in r["CHAIN-02"].reason


def test_missing_tin_fails():
    r = run(trade(FATHER))
    assert {v.outcome for v in r.values()} == {Outcome.FAIL}
    assert "no TIN Certificate" in r["CHAIN-02"].reason


def test_two_trade_licenses_flag():
    r = run(tin(FATHER), trade(FATHER, doc_id="t1"), trade(MOTHER, doc_id="t2"))
    assert {v.outcome for v in r.values()} == {Outcome.FLAG}


def test_bank_does_not_change_chain_02_or_03():
    student_bank = BankSolvency(doc_id="bank")
    r = run(tin(FATHER), trade(FATHER), student_bank)
    assert overall(r.values()) is Outcome.PASS


# --- CHAIN-04: bank account holder = trade licence owner (RULES-v6) ---------------


def test_bank_holder_same_parent_as_trade_owner_passes():
    [r] = chain04(trade(FATHER), bank_solvency(holder=FATHER))
    assert r.outcome is Outcome.PASS
    assert "Father" in r.reason


def test_bank_holder_other_parent_fails():
    [r] = chain04(trade(FATHER), bank_solvency(holder=MOTHER))
    assert r.outcome is Outcome.FAIL
    assert "account holder is the Mother but the Trade License owner is the Father" in r.reason


def test_bank_in_student_name_fails():
    [r] = chain04(trade(FATHER), bank_solvency(holder=STUDENT))
    assert r.outcome is Outcome.FAIL


def test_low_confidence_bank_holder_flags():
    [r] = chain04(trade(FATHER), bank_solvency(holder=FATHER, confidence=LOW))
    assert r.outcome is Outcome.FLAG
    assert "low OCR confidence" in r.reason


def test_employment_certificate_is_the_income_link_too():
    [r] = chain04(employment(MOTHER), bank_solvency(holder=MOTHER))
    assert r.outcome is Outcome.PASS


def test_one_result_per_solvency_and_missing_links_fail():
    rs = chain04(trade(FATHER), bank_solvency(holder=FATHER, doc_id="b1"), bank_solvency(holder=MOTHER, doc_id="b2"))
    assert [r.outcome for r in rs] == [Outcome.PASS, Outcome.FAIL]
    [r] = chain04(trade(FATHER))
    assert r.outcome is Outcome.FAIL and "no Bank Solvency" in r.reason


def test_two_income_documents_flag():
    [r] = chain04(trade(FATHER, doc_id="t1"), trade(FATHER, doc_id="t2"), bank_solvency(holder=FATHER))
    assert r.outcome is Outcome.FLAG


def test_uncertain_father_anchor_flags():
    from builders import birth_certificate, passport
    from hklv_rules.context import EvaluationContext
    from hklv_rules.models import CaseFile
    from builders import EVAL_DATE

    case = CaseFile(
        case_id="t",
        evaluation_date=EVAL_DATE,
        documents=(passport(), birth_certificate(confidence=LOW), tin(FATHER), trade(FATHER)),
    )
    r = by_rule(check_financial_chain(EvaluationContext.build(case)))
    assert r["CHAIN-02"].outcome is Outcome.FLAG

"""Master Verdict Engine (Rulebook section 6): any FAIL -> FAIL, else any FLAG -> FLAG, else PASS."""

import itertools

import pytest
from builders import (
    FATHER,
    MOTHER,
    bank_solvency,
    bank_statement,
    case_file,
    complete_case_documents,
    death,
    employment,
    tin,
    trade,
)

from hklv_rules.engine import COVERAGE_RULE, NOT_YET_IMPLEMENTED, evaluate_case, final_verdict, run_all_rules
from hklv_rules.context import EvaluationContext
from hklv_rules.models import BankSolvency, BankStatement, NationalId, Outcome, RuleResult, TinCertificate, TradeLicense

P, G, F = Outcome.PASS, Outcome.FLAG, Outcome.FAIL


def r(outcome: Outcome, rule_id: str = "X-01") -> RuleResult:
    return RuleResult(rule_id=rule_id, outcome=outcome, reason=f"{rule_id} {outcome.value}")


# --- final_verdict: the three rules of section 6 ----------------------------------


def test_all_pass_is_pass():
    v = final_verdict([r(P, "A"), r(P, "B"), r(P, "C")])
    assert v.outcome is P
    assert v.summary == "PASS: all 3 checks passed"
    assert v.failures == () and v.flags == ()


def test_any_flag_without_fail_is_flag():
    v = final_verdict([r(P, "A"), r(G, "B"), r(P, "C")])
    assert v.outcome is G
    assert "B" in v.summary
    assert [x.rule_id for x in v.flags] == ["B"]


def test_any_fail_is_fail():
    v = final_verdict([r(P, "A"), r(F, "B"), r(P, "C")])
    assert v.outcome is F
    assert [x.rule_id for x in v.failures] == ["B"]


def test_fail_beats_flag():
    v = final_verdict([r(G, "A"), r(F, "B"), r(G, "C")])
    assert v.outcome is F
    assert "failed (B)" in v.summary and "flagged (A, C)" in v.summary


def test_single_fail_among_many_passes_is_fail():
    assert final_verdict([r(P)] * 50 + [r(F)]).outcome is F


@pytest.mark.parametrize("combo", list(itertools.product([P, G, F], repeat=3)))
def test_every_combination_follows_section_6(combo):
    expected = F if F in combo else G if G in combo else P
    assert final_verdict([r(o) for o in combo]).outcome is expected


def test_order_does_not_matter():
    results = [r(P, "A"), r(G, "B"), r(F, "C")]
    for perm in itertools.permutations(results):
        assert final_verdict(perm).outcome is F


def test_accepts_any_iterable_and_keeps_every_result():
    v = final_verdict(x for x in [r(P, "A"), r(G, "B")])
    assert [x.rule_id for x in v.results] == ["A", "B"]


def test_repeated_rule_ids_are_listed_once_in_summary():
    v = final_verdict([r(F, "FRC-04"), r(F, "FRC-04"), r(F, "CHAIN-02")])
    assert v.summary.startswith("FAIL: 2 rule(s) failed (FRC-04, CHAIN-02)")
    assert len(v.failures) == 3


def test_empty_list_is_flag_never_pass():
    v = final_verdict([])
    assert v.outcome is G
    assert "nothing was checked" in v.summary


# --- evaluate_case: every rule written so far, end to end --------------------------


def outcomes_without_coverage(verdict):
    return {x.outcome for x in verdict.results if x.rule_id != COVERAGE_RULE}


def test_every_rule_group_is_implemented():
    assert NOT_YET_IMPLEMENTED == ()


def test_clean_case_passes_every_rule():
    v = evaluate_case(case_file(*complete_case_documents()))
    assert v.outcome is P, [(x.rule_id, x.reason) for x in v.results if x.outcome is not P]
    assert COVERAGE_RULE not in {x.rule_id for x in v.results}


def test_a_rule_missing_from_the_engine_keeps_every_case_flagged(monkeypatch):
    monkeypatch.setattr("hklv_rules.engine.NOT_YET_IMPLEMENTED", ("NEW-01",))
    v = evaluate_case(case_file(*complete_case_documents()))
    assert v.outcome is G
    [cov] = [x for x in v.results if x.rule_id == COVERAGE_RULE]
    assert "NEW-01" in cov.reason


def test_missing_optional_documents_do_not_flag():
    # No Income Tax, no Student NID, no IELTS/TOPIK in the clean case: still a clean PASS.
    v = evaluate_case(case_file(*complete_case_documents()))
    by_id = {x.rule_id: x for x in v.results}
    assert by_id["REQ-10"].outcome is P and "IELTS/TOPIK not submitted" in by_id["REQ-10"].reason
    assert by_id["TAX-01"].outcome is P
    assert not any(x.rule_id.startswith("LANG-") for x in v.results)


def test_tin_father_and_trade_mother_fails_the_case():
    docs = [d for d in complete_case_documents() if not isinstance(d, (TinCertificate, TradeLicense))]
    v = evaluate_case(case_file(*docs, tin(FATHER), trade(MOTHER)))
    assert v.outcome is F
    assert "CHAIN-02" in {x.rule_id for x in v.failures}


def test_deceased_father_with_death_certificate_and_employed_mother():
    docs = [
        d
        for d in complete_case_documents()
        if not isinstance(d, (TinCertificate, TradeLicense, BankSolvency, BankStatement))
        and getattr(d, "doc_id", "") != "n-father"
    ]
    # the whole chain is the mother's: TIN, employment and (CHAIN-04) the bank account
    bank = (bank_solvency(holder=MOTHER), bank_statement(holder=MOTHER))
    v = evaluate_case(case_file(*docs, death(FATHER), tin(MOTHER), employment(MOTHER), *bank))
    assert outcomes_without_coverage(v) == {P}, [x for x in v.results if x.outcome is not P]


def test_missing_parent_identity_fails_the_case():
    docs = [d for d in complete_case_documents() if not isinstance(d, NationalId)]
    v = evaluate_case(case_file(*docs))
    assert v.outcome is F
    assert {"REQ-08", "REQ-09"} <= {x.rule_id for x in v.failures}


def test_run_all_rules_covers_each_rule_group():
    ids = {x.rule_id for x in run_all_rules(EvaluationContext.build(case_file(*complete_case_documents(), employment())))}
    for expected in (
        "REQ-01", "PASSPORT-01", "NID-ASSIGN", "NID-01", "NID-02", "NID-03", "BIRTH-01", "BIRTH-04", "BIRTH-05",
        "FRC-01", "BANK-01", "BANK-04", "TRADE-01", "TRADE-04", "EMP-01", "TIN-01", "TIN-03",
        "ACAD-01", "ACAD-02", "ACAD-03", "ACAD-04", "TAX-01", "CHAIN-02",
    ):
        assert expected in ids, expected
    assert COVERAGE_RULE not in ids


def test_death_certificate_rule_results_reach_the_final_verdict():
    docs = [d for d in complete_case_documents() if getattr(d, "doc_id", "") != "n-father"]
    v = evaluate_case(case_file(*docs, death(FATHER, notary=None)))
    assert v.outcome is F
    assert "DEATH-03" in {x.rule_id for x in v.failures}

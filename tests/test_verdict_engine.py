"""Master Verdict Engine (Rulebook section 6): any FAIL -> FAIL, else any FLAG -> FLAG, else PASS."""

import itertools

import pytest
from builders import FATHER, MOTHER, case_file, complete_case_documents, death, employment, tin, trade

from hklv_rules.engine import COVERAGE_RULE, NOT_YET_IMPLEMENTED, evaluate_case, final_verdict, run_all_rules
from hklv_rules.context import EvaluationContext
from hklv_rules.models import NationalId, Outcome, RuleResult, TinCertificate, TradeLicense

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


def test_clean_case_passes_every_rule_but_coverage_keeps_it_flagged():
    v = evaluate_case(case_file(*complete_case_documents()))
    assert outcomes_without_coverage(v) == {P}
    assert v.outcome is G  # the engine is not complete yet: never a clean PASS
    assert [x.rule_id for x in v.flags] == [COVERAGE_RULE]


def test_clean_case_would_pass_once_every_rule_is_written(monkeypatch):
    monkeypatch.setattr("hklv_rules.engine.NOT_YET_IMPLEMENTED", ())
    assert evaluate_case(case_file(*complete_case_documents())).outcome is P


def test_coverage_flag_lists_missing_rules():
    v = evaluate_case(case_file(*complete_case_documents()))
    [cov] = [x for x in v.results if x.rule_id == COVERAGE_RULE]
    assert all(rule in cov.reason for rule in NOT_YET_IMPLEMENTED)


def test_tin_father_and_trade_mother_fails_the_case():
    docs = [d for d in complete_case_documents() if not isinstance(d, (TinCertificate, TradeLicense))]
    v = evaluate_case(case_file(*docs, tin(FATHER), trade(MOTHER)))
    assert v.outcome is F
    assert "CHAIN-02" in {x.rule_id for x in v.failures}


def test_deceased_father_with_death_certificate_and_employed_mother():
    docs = [
        d
        for d in complete_case_documents()
        if not isinstance(d, (TinCertificate, TradeLicense)) and getattr(d, "doc_id", "") != "n-father"
    ]
    v = evaluate_case(case_file(*docs, death(FATHER), tin(MOTHER), employment(MOTHER)))
    assert outcomes_without_coverage(v) == {P}, [x for x in v.results if x.outcome is not P]


def test_missing_parent_identity_fails_the_case():
    docs = [d for d in complete_case_documents() if not isinstance(d, NationalId)]
    v = evaluate_case(case_file(*docs))
    assert v.outcome is F
    assert {"REQ-08", "REQ-09"} <= {x.rule_id for x in v.failures}


def test_run_all_rules_covers_each_rule_group():
    ids = {x.rule_id for x in run_all_rules(EvaluationContext.build(case_file(*complete_case_documents(), employment())))}
    for expected in ("REQ-01", "NID-ASSIGN", "FRC-01", "EMP-01", "CHAIN-01", COVERAGE_RULE):
        assert expected in ids


def test_death_certificate_rule_results_reach_the_final_verdict():
    docs = [d for d in complete_case_documents() if getattr(d, "doc_id", "") != "n-father"]
    v = evaluate_case(case_file(*docs, death(FATHER, notary=None)))
    assert v.outcome is F
    assert "DEATH-03" in {x.rule_id for x in v.failures}

"""The master Verdict Engine (Rulebook v2.5 section 6).

`final_verdict` turns a list of rule results into the overall verdict:
    any FAIL -> FAIL;  else any FLAG -> FLAG;  else PASS.

`evaluate_case` runs every Rulebook v2.5 rule on one student's documents and returns that
verdict. NOT_YET_IMPLEMENTED is kept as a safety net: anything listed there is reported as
an ENGINE-COVERAGE FLAG, so an incomplete engine can never hand out a clean PASS.
"""

from __future__ import annotations

from collections.abc import Iterable

from .context import EvaluationContext
from .models import DEFAULT_CONFIDENCE_THRESHOLD, CaseFile, CaseVerdict, Outcome, RuleResult, worst
from .rules import (
    assign_nids,
    check_academic,
    check_bank,
    check_birth_certificates,
    check_death_certificates,
    check_employment,
    check_financial_chain,
    check_frc,
    check_income_tax,
    check_language_tests,
    check_nids,
    check_passport,
    check_required_documents,
    check_tin,
    check_trade_licenses,
)

COVERAGE_RULE = "ENGINE-COVERAGE"

# Every rule group of Rulebook v2.5 is implemented. If a rule is ever added to the
# rulebook before its code, list it here: every case then gets a FLAG until it lands.
NOT_YET_IMPLEMENTED: tuple[str, ...] = ()


def final_verdict(results: Iterable[RuleResult]) -> CaseVerdict:
    """Overall verdict from all rule results: any FAIL -> FAIL, else any FLAG -> FLAG, else PASS.

    An empty list is FLAG, not PASS: no results means nothing was checked, and "nothing
    checked" must never read as "valid".
    """
    results = tuple(results)
    if not results:
        return CaseVerdict(
            outcome=Outcome.FLAG,
            summary="No rule results were produced; nothing was checked, so manual review is required",
            results=(),
        )

    outcome = worst(r.outcome for r in results)
    fails = _rule_ids(r for r in results if r.outcome is Outcome.FAIL)
    flags = _rule_ids(r for r in results if r.outcome is Outcome.FLAG)
    if outcome is Outcome.FAIL:
        summary = f"FAIL: {len(fails)} rule(s) failed ({', '.join(fails)})"
        if flags:
            summary += f"; {len(flags)} also flagged ({', '.join(flags)})"
    elif outcome is Outcome.FLAG:
        summary = f"FLAG: needs manual review; {len(flags)} rule(s) flagged ({', '.join(flags)})"
    else:
        summary = f"PASS: all {len(results)} checks passed"
    return CaseVerdict(outcome=outcome, summary=summary, results=results)


def _rule_ids(results: Iterable[RuleResult]) -> list[str]:
    """Distinct rule ids in first-seen order (FRC rules repeat per FRC, NID-ASSIGN per NID)."""
    return list(dict.fromkeys(r.rule_id for r in results))


def run_all_rules(ctx: EvaluationContext) -> list[RuleResult]:
    nids = assign_nids(ctx)
    deaths = check_death_certificates(ctx)
    results = [
        *check_required_documents(ctx, nids, deaths),  # section 3
        *check_passport(ctx),  # 4.1
        *nids.results,  # 2.2
        *check_nids(ctx, nids),  # 4.2
        *deaths.results,
        *check_birth_certificates(ctx),  # 4.3
        *check_frc(ctx),  # 4.4
        *check_bank(ctx),  # 4.5
        *check_trade_licenses(ctx),  # 4.6
        *check_employment(ctx),  # 4.6 (Employment Certificate, supplement)
        *check_tin(ctx),  # 4.7
        *check_academic(ctx),  # 4.8
        *check_income_tax(ctx),  # 4.9 (optional)
        *check_language_tests(ctx),  # 4.10 (optional)
        *check_financial_chain(ctx),  # 5.1
    ]
    if NOT_YET_IMPLEMENTED:
        results.append(
            RuleResult(
                rule_id=COVERAGE_RULE,
                outcome=Outcome.FLAG,
                reason="Rules not yet implemented, check by hand: " + ", ".join(NOT_YET_IMPLEMENTED),
            )
        )
    return results


def evaluate_case(case: CaseFile, threshold: float = DEFAULT_CONFIDENCE_THRESHOLD) -> CaseVerdict:
    return final_verdict(run_all_rules(EvaluationContext.build(case, threshold)))

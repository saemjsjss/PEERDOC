"""Rulebook v2.5 section 4.6: Trade License (TRADE-01 .. TRADE-04).

One result per rule per Trade License. An Employment Certificate may replace the Trade
License (REQ-06); it has its own EMP rules, so it is ignored here. No Trade License ->
no results (REQ-06 reports the absence).
"""

from __future__ import annotations

import re
from datetime import date

from ..context import EvaluationContext
from ..models import Outcome, Person, RuleResult, TradeLicense
from ._evidence import ev
from ._shared import assign_by_name, notary_rule, translation_rule

TRADE_01, TRADE_02, TRADE_03, TRADE_04 = "TRADE-01", "TRADE-02", "TRADE-03", "TRADE-04"
ALL_RULES = (TRADE_01, TRADE_02, TRADE_03, TRADE_04)

# '2026-2027', '2026-27', '2026/2027', '2026 - 27', also Bangla digits ('২০২৬-২০২৭'):
# Python's \d and int() both accept any Unicode decimal digit.
_FISCAL_YEAR = re.compile(r"(?<!\d)(\d{4})\s*[-/–—]\s*(\d{4}|\d{2})(?!\d)")


def check_trade_licenses(ctx: EvaluationContext) -> list[RuleResult]:
    results: list[RuleResult] = []
    for t in ctx.case.of_kind(TradeLicense):
        results += [
            _named(translation_rule(TRADE_01, t.doc_id, t.language, t.has_english_translation, ctx), t.doc_id),
            _named(notary_rule(TRADE_02, t.doc_id, t.notary, ctx), t.doc_id),
            _trade_03_fiscal_year(t, ctx),
            _trade_04_owner(t, ctx),
        ]
    return results


def _named(r: RuleResult, doc_id: str) -> RuleResult:
    """Prefix a shared helper's reason with the document it is about."""
    return r.model_copy(update={"reason": f"Trade License {doc_id}: {r.reason}"})


# --- TRADE-03 Fiscal year ---------------------------------------------------------


def current_fiscal_year(d: date) -> tuple[int, int]:
    """Bangladesh fiscal year runs July-June: 10-11-2026 is in 2026-2027, 30-06-2027 too."""
    return (d.year, d.year + 1) if d.month >= 7 else (d.year - 1, d.year)


def parse_fiscal_year(text: str) -> tuple[int, int] | None:
    """(start, end) from '2026-2027' / '2026-27' / '2026/2027'; None if unreadable, if the
    end year is not start + 1, or if the text names more than one fiscal year."""
    found: set[tuple[int, int]] = set()
    for start_s, end_s in _FISCAL_YEAR.findall(text):
        start, end = int(start_s), int(end_s)
        if len(end_s) == 2:
            if end != (start + 1) % 100:
                return None
            end = start + 1
        if end != start + 1:
            return None
        found.add((start, end))
    return found.pop() if len(found) == 1 else None


def _fy(fy: tuple[int, int]) -> str:
    return f"{fy[0]}-{fy[1]}"


def _trade_03_fiscal_year(t: TradeLicense, ctx: EvaluationContext) -> RuleResult:
    evidence = (ev(t.doc_id, "fiscal_year", t.fiscal_year),)

    def result(outcome: Outcome, reason: str) -> RuleResult:
        return RuleResult(
            rule_id=TRADE_03, outcome=outcome, reason=f"Trade License {t.doc_id}: {reason}", evidence=evidence
        )

    today = ctx.case.evaluation_date
    current = current_fiscal_year(today)
    if not (t.fiscal_year.found and t.fiscal_year.value.strip()):
        return result(Outcome.FLAG, "fiscal year not found")
    if not t.fiscal_year.is_reliable(ctx.threshold):
        return result(Outcome.FLAG, f"fiscal year '{t.fiscal_year.value}' read with low OCR confidence")
    fy = parse_fiscal_year(t.fiscal_year.value)
    if fy is None:
        return result(Outcome.FLAG, f"fiscal year '{t.fiscal_year.value}' could not be read as a July-June year")
    context = f"current fiscal year on {today:%d-%m-%Y} is {_fy(current)} (July-June)"
    if fy == current:
        return result(Outcome.PASS, f"fiscal year {_fy(fy)} is current; {context}")
    if fy < current:
        return result(Outcome.FAIL, f"fiscal year {_fy(fy)} is older than the current one; {context}")
    return result(Outcome.FLAG, f"fiscal year {_fy(fy)} is later than the current one (likely misread); {context}")


# --- TRADE-04 Owner -----------------------------------------------------------------


def _trade_04_owner(t: TradeLicense, ctx: EvaluationContext) -> RuleResult:
    assignment = assign_by_name(
        TRADE_04,
        "Trade License",
        [(t.doc_id, "owner_name", t.owner_name)],
        ctx,
        allowed=(Person.FATHER, Person.MOTHER),
        unknown_reason="is not in the father's or mother's name",
    )
    return assignment.results[0]

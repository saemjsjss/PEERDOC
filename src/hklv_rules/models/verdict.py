"""Structured outcomes every rule returns."""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum

from .common import Frozen


class Outcome(str, Enum):
    PASS = "PASS"
    FLAG = "FLAG"  # uncertain: needs manual review
    FAIL = "FAIL"  # hard error / forgery

    @property
    def severity(self) -> int:
        return {"PASS": 0, "FLAG": 1, "FAIL": 2}[self.value]


class Evidence(Frozen):
    doc_id: str
    field: str
    value: str | None = None
    page: int | None = None


class RuleResult(Frozen):
    rule_id: str
    outcome: Outcome
    reason: str
    evidence: tuple[Evidence, ...] = ()


def worst(outcomes: Iterable[Outcome]) -> Outcome:
    """Rulebook section 6: any FAIL -> FAIL, else any FLAG -> FLAG, else PASS."""
    return max(outcomes, key=lambda o: o.severity, default=Outcome.PASS)


def overall(results: Iterable[RuleResult]) -> Outcome:
    return worst(r.outcome for r in results)

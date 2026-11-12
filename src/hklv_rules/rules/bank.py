"""Rulebook v2.5 section 4.5: Bank Solvency & Statement (BANK-01 .. BANK-04).

BANK-01..03 give one result per Bank Solvency letter. The solvency is paired with the
statement whose account number matches it (BANK-02); BANK-03 then compares the letter
date with that statement's date. A pairing counts only when both account numbers are read
reliably (or there is a single statement); otherwise BANK-03 compares the letter date with
every statement that could be the pair and FLAGs, never FAILs, when none matches.
A missing solvency or statement also fails REQ-05;
these rules FAIL too, because there is nothing to compare against.
"""

from __future__ import annotations

from datetime import date

from ..context import EvaluationContext
from ..models import BankSolvency, BankStatement, Extracted, Outcome, Person, RuleResult
from ._evidence import ev
from ._shared import assign_by_name, digits

BANK_01, BANK_02, BANK_03, BANK_04 = "BANK-01", "BANK-02", "BANK-03", "BANK-04"
ALL_RULES = (BANK_01, BANK_02, BANK_03, BANK_04)

_NO_SOLVENCY = "No bank solvency letter found"
_NO_STATEMENT = "No bank statement to compare against"


def check_bank(ctx: EvaluationContext) -> list[RuleResult]:
    solvencies = ctx.case.of_kind(BankSolvency)
    statements = ctx.case.of_kind(BankStatement)
    if not solvencies:
        return [
            *(RuleResult(rule_id=r, outcome=Outcome.FAIL, reason=_NO_SOLVENCY) for r in (BANK_01, BANK_02, BANK_03)),
            _bank_04(solvencies, statements),
        ]
    results: list[RuleResult] = []
    for s in solvencies:
        results += [
            _bank_01_holder(s, ctx),
            _bank_02_account(s, statements, ctx),
            _bank_03_date(s, statements, ctx),
        ]
    results.append(_bank_04(solvencies, statements))
    return results


# --- BANK-01 Holder -------------------------------------------------------------


def _bank_01_holder(s: BankSolvency, ctx: EvaluationContext) -> RuleResult:
    """Account holder must be the father or mother; the student (or anyone else) FAILs."""
    assignment = assign_by_name(
        BANK_01,
        "Bank Solvency",
        [(s.doc_id, "account_holder", s.account_holder)],
        ctx,
        allowed=(Person.FATHER, Person.MOTHER),
        unknown_reason="is not in the father's or mother's name",
    )
    return assignment.results[0]


# --- BANK-02 Account number -----------------------------------------------------


def _usable_number(x: Extracted[str], ctx: EvaluationContext) -> str | None:
    """The account number's digits when read reliably, else None."""
    return digits(x.value) if x.is_reliable(ctx.threshold) and digits(x.value) else None


def _bank_02_account(s: BankSolvency, statements: list[BankStatement], ctx: EvaluationContext) -> RuleResult:
    evidence = (
        ev(s.doc_id, "account_number", s.account_number),
        *(ev(st.doc_id, "account_number", st.account_number) for st in statements),
    )

    def result(outcome: Outcome, reason: str) -> RuleResult:
        return RuleResult(
            rule_id=BANK_02, outcome=outcome, reason=f"Bank Solvency {s.doc_id}: {reason}", evidence=evidence
        )

    if not statements:
        return result(Outcome.FAIL, _NO_STATEMENT)
    if not (s.account_number.found and digits(s.account_number.value)):
        return result(Outcome.FLAG, "account number not found, so it can't be compared with the statement")
    mine = _usable_number(s.account_number, ctx)
    if mine is None:
        # A misread can't land exactly on the statement's (reliably read) long account number.
        shaky = digits(s.account_number.value)
        exact = [st for st in statements if len(shaky) >= 8 and _usable_number(st.account_number, ctx) == shaky]
        if exact:
            return result(
                Outcome.PASS,
                f"account number {shaky} (low OCR confidence) matches Bank Statement {exact[0].doc_id} exactly",
            )
        return result(Outcome.FLAG, f"account number '{s.account_number.value}' read with low OCR confidence")

    # an exact match also confirms a statement number read with low confidence
    exact_ok = len(mine) >= 8
    matched = [
        st
        for st in statements
        if _usable_number(st.account_number, ctx) == mine or (exact_ok and digits(st.account_number.value) == mine)
    ]
    if matched:
        return result(Outcome.PASS, f"account number {mine} matches Bank Statement {matched[0].doc_id}")

    unreadable = [st.doc_id for st in statements if _usable_number(st.account_number, ctx) is None]
    if unreadable:
        return result(
            Outcome.FLAG,
            f"account number {mine} matches no readable statement; account number on Bank Statement "
            f"{', '.join(unreadable)} is missing or read with low OCR confidence",
        )
    others = ", ".join(f"{st.doc_id} {digits(st.account_number.value)}" for st in statements)
    return result(Outcome.FAIL, f"account number {mine} does not match the Bank Statement ({others})")


# --- BANK-03 Date match ---------------------------------------------------------


def _plausible_pair(s: BankSolvency, st: BankStatement, ctx: EvaluationContext) -> bool:
    """False only when both account numbers are read reliably and differ."""
    mine, theirs = _usable_number(s.account_number, ctx), _usable_number(st.account_number, ctx)
    return mine is None or theirs is None or mine == theirs


def _paired_statements(
    s: BankSolvency, statements: list[BankStatement], ctx: EvaluationContext
) -> tuple[list[BankStatement], bool]:
    """(statements to compare with, whether that pairing is decisive).

    Decisive: the statements whose account number reliably equals the solvency's (both
    numbers read reliably), else the only statement. An equality that rests on
    low-confidence digits decides nothing, so with several statements and no reliable
    match the list is not narrowed by number: every statement that could be the pair
    (see _plausible_pair) is returned, not decisive."""
    mine = _usable_number(s.account_number, ctx)
    if mine is not None:
        matched = [st for st in statements if _usable_number(st.account_number, ctx) == mine]
        if matched:
            return matched, True
    if len(statements) == 1:
        return list(statements), True
    return [st for st in statements if _plausible_pair(s, st, ctx)], False


def _uncertain_pairing(s: BankSolvency, statements: list[BankStatement], ctx: EvaluationContext) -> str:
    numbers = (s.account_number, *(st.account_number for st in statements))
    if any(x.found and digits(x.value) and not x.is_reliable(ctx.threshold) for x in numbers):
        return "pairing uncertain: account number read with low OCR confidence"
    return "pairing uncertain: account number missing"


def _bank_03_date(s: BankSolvency, statements: list[BankStatement], ctx: EvaluationContext) -> RuleResult:
    paired, decisive = _paired_statements(s, statements, ctx)
    evidence = (
        ev(s.doc_id, "letter_date", s.letter_date),
        *(ev(st.doc_id, "statement_date", st.statement_date) for st in (paired if decisive else statements)),
    )

    def result(outcome: Outcome, reason: str) -> RuleResult:
        return RuleResult(
            rule_id=BANK_03, outcome=outcome, reason=f"Bank Solvency {s.doc_id}: {reason}", evidence=evidence
        )

    if not statements:
        return result(Outcome.FAIL, _NO_STATEMENT)
    if not paired:
        return result(
            Outcome.FLAG,
            "several bank statements and none shares the solvency's account number; "
            "could not tell which statement date to compare with",
        )
    if not s.letter_date.found:
        return result(Outcome.FLAG, "solvency letter date not found")
    if not s.letter_date.is_reliable(ctx.threshold):
        return result(Outcome.FLAG, "solvency letter date read with low OCR confidence")
    letter: date = s.letter_date.value

    reliable = [st for st in paired if st.statement_date.is_reliable(ctx.threshold)]
    same = [st for st in reliable if st.statement_date.value == letter]
    if same:
        how = "" if decisive else f" ({_uncertain_pairing(s, statements, ctx)}; paired by date)"
        return result(
            Outcome.PASS, f"letter date {letter:%d-%m-%Y} matches Bank Statement {same[0].doc_id} date exactly{how}"
        )
    if not decisive:
        dates = ", ".join(
            f"{st.doc_id} {st.statement_date.value:%d-%m-%Y}"
            if st in reliable
            else f"{st.doc_id} ({'read with low OCR confidence' if st.statement_date.found else 'not found'})"
            for st in paired
        )
        return result(
            Outcome.FLAG,
            f"{_uncertain_pairing(s, statements, ctx)}; letter date {letter:%d-%m-%Y} "
            f"matches no statement date ({dates})",
        )
    shaky = [st for st in paired if st not in reliable]
    if shaky:
        what = ", ".join(
            f"{st.doc_id} ({'read with low OCR confidence' if st.statement_date.found else 'not found'})"
            for st in shaky
        )
        return result(Outcome.FLAG, f"letter date {letter:%d-%m-%Y}; statement date on Bank Statement {what}")
    others = ", ".join(f"{st.doc_id} {st.statement_date.value:%d-%m-%Y}" for st in reliable)
    return result(Outcome.FAIL, f"letter date {letter:%d-%m-%Y} does not match the statement date ({others})")


# --- BANK-04 Minimum balance ------------------------------------------------------


def _bank_04(solvencies: list[BankSolvency], statements: list[BankStatement]) -> RuleResult:
    """Rulebook: 'Do not check. PASS.' One result per case."""
    ids = [d.doc_id for d in (*solvencies, *statements)]
    if ids:
        reason = f"Minimum balance not checked (Rulebook BANK-04: do not check); bank documents {', '.join(ids)}"
    else:
        reason = "Minimum balance not checked (Rulebook BANK-04: do not check); no bank documents to check"
    return RuleResult(rule_id=BANK_04, outcome=Outcome.PASS, reason=reason)

"""Pass 2, section 2.1: establish StudentRef, FatherRef and MotherRef.

An anchor is 'certain' only when its source was read reliably and agrees with
itself. Comparisons against an uncertain anchor yield FLAG, never a guess.
"""

from __future__ import annotations

from collections.abc import Sequence

from .models import BirthCertificate, CaseFile, Extracted, Passport, Person
from .models.common import Frozen
from .names import normalize_name


class Anchor(Frozen):
    person: Person
    name: str | None = None
    certain: bool = False
    source: str = "none"
    note: str = ""

    def describe(self) -> str:
        if self.name is None:
            return f"{self.person.ref_label} (not established: {self.note})"
        return f"{self.person.ref_label} '{self.name}'"


class Anchors(Frozen):
    student: Anchor
    father: Anchor
    mother: Anchor

    def for_person(self, person: Person) -> Anchor:
        return {Person.STUDENT: self.student, Person.FATHER: self.father, Person.MOTHER: self.mother}[person]


def establish_anchors(case: CaseFile, threshold: float) -> Anchors:
    passports = case.of_kind(Passport)
    births = case.of_kind(BirthCertificate)
    return Anchors(
        student=_student_anchor(passports, threshold),
        father=_parent_anchor(
            Person.FATHER,
            [b.father_name for b in births],
            [p.father_name for p in passports],
            threshold,
        ),
        mother=_parent_anchor(
            Person.MOTHER,
            [b.mother_name for b in births],
            [p.mother_name for p in passports],
            threshold,
        ),
    )


def _join(parts: Sequence[Extracted[str]], threshold: float) -> tuple[str, bool]:
    """Join name parts that were found; second value is False if any found part is unreliable."""
    found = [p for p in parts if p.found and p.value.strip()]
    reliable = all(p.is_reliable(threshold) for p in found)
    return " ".join(p.value.strip() for p in found), reliable


def _student_anchor(passports: list[Passport], threshold: float) -> Anchor:
    if not passports:
        return Anchor(person=Person.STUDENT, note="no passport")

    candidates: list[Anchor] = []
    for p in passports:
        printed, printed_ok = _join([p.given_names, p.surname], threshold)
        mrz, mrz_ok = _join([p.mrz_given_names, p.mrz_surname], threshold)
        if not printed:
            candidates.append(Anchor(person=Person.STUDENT, note=f"passport {p.doc_id}: printed name not found"))
            continue
        problems = []
        if not printed_ok:
            problems.append("printed name has low OCR confidence")
        if not mrz:
            problems.append("MRZ name not found")
        elif not mrz_ok:
            problems.append("MRZ name has low OCR confidence")
        elif normalize_name(mrz) != normalize_name(printed):
            problems.append(f"MRZ name '{mrz}' differs from printed name '{printed}'")
        candidates.append(
            Anchor(
                person=Person.STUDENT,
                name=printed,
                certain=not problems,
                source=f"Passport {p.doc_id}",
                note="; ".join(problems),
            )
        )
    return _merge(Person.STUDENT, candidates)


def _parent_anchor(
    person: Person,
    from_birth: list[Extracted[str]],
    from_passport: list[Extracted[str]],
    threshold: float,
) -> Anchor:
    # Birth Certificate is primary. The passport is a fallback only when no Birth
    # Certificate carries the field at all: an unreadable Birth Certificate value is
    # uncertainty (FLAG), not a reason to silently switch sources.
    birth_found = [e for e in from_birth if e.found]
    if birth_found:
        return _merge(person, [_from_field(person, e, "Birth Certificate", threshold) for e in birth_found])
    passport_found = [e for e in from_passport if e.found]
    if passport_found:
        return _merge(person, [_from_field(person, e, "Passport (fallback)", threshold) for e in passport_found])
    return Anchor(person=person, note="no Birth Certificate or Passport value")


def _from_field(person: Person, e: Extracted[str], source: str, threshold: float) -> Anchor:
    ok = e.is_reliable(threshold) and bool(normalize_name(e.value))
    return Anchor(
        person=person,
        name=e.value.strip(),
        certain=ok,
        source=source,
        note="" if ok else f"{source} value has low OCR confidence",
    )


def _merge(person: Person, candidates: list[Anchor]) -> Anchor:
    named = [c for c in candidates if c.name is not None]
    if not named:
        return candidates[0] if candidates else Anchor(person=person)
    first = named[0]
    keys = {normalize_name(c.name) for c in named}
    if len(keys) > 1:
        names = ", ".join(f"'{c.name}' ({c.source})" for c in named)
        return first.model_copy(update={"certain": False, "note": f"sources disagree: {names}"})
    if not all(c.certain for c in named):
        notes = "; ".join(c.note for c in named if c.note)
        return first.model_copy(update={"certain": False, "note": notes})
    return first

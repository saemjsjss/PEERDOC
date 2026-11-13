"""Everything a rule needs, built once per case."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .anchors import Anchors, establish_anchors
from .models import DEFAULT_CONFIDENCE_THRESHOLD, Affidavit, CaseFile, EmploymentCertificate, Extracted, Person


@dataclass(frozen=True)
class EvaluationContext:
    case: CaseFile
    anchors: Anchors
    threshold: float
    affidavits: tuple[Affidavit, ...]

    @classmethod
    def build(cls, case: CaseFile, threshold: float = DEFAULT_CONFIDENCE_THRESHOLD) -> EvaluationContext:
        ctx = cls(
            case=case,
            anchors=establish_anchors(case, threshold),
            threshold=threshold,
            affidavits=tuple(case.of_kind(Affidavit)),
        )
        # RULES-v8: an employment / experience letter reliably in the student's own name is
        # the student's CV, not a sponsor's income document: skip it like an IGNORE-01 page.
        from .identity import MatchKind, compare_name

        own = {
            e.doc_id
            for e in case.of_kind(EmploymentCertificate)
            if compare_name(e.employee_name, Person.STUDENT, ctx).kind in (MatchKind.EXACT, MatchKind.AFFIDAVIT)
        }
        if not own:
            return ctx
        kept = tuple(d for d in case.documents if d.doc_id not in own)
        return replace(ctx, case=case.model_copy(update={"documents": kept}))

    def tri_state(self, value: Extracted[bool]) -> bool | None:
        """True/False when read reliably, None when missing or low confidence."""
        return value.value if value.is_reliable(self.threshold) else None

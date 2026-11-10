"""Everything a rule needs, built once per case."""

from __future__ import annotations

from dataclasses import dataclass

from .anchors import Anchors, establish_anchors
from .models import DEFAULT_CONFIDENCE_THRESHOLD, Affidavit, CaseFile, Extracted


@dataclass(frozen=True)
class EvaluationContext:
    case: CaseFile
    anchors: Anchors
    threshold: float
    affidavits: tuple[Affidavit, ...]

    @classmethod
    def build(cls, case: CaseFile, threshold: float = DEFAULT_CONFIDENCE_THRESHOLD) -> "EvaluationContext":
        return cls(
            case=case,
            anchors=establish_anchors(case, threshold),
            threshold=threshold,
            affidavits=tuple(case.of_kind(Affidavit)),
        )

    def tri_state(self, value: Extracted[bool]) -> bool | None:
        """True/False when read reliably, None when missing or low confidence."""
        return value.value if value.is_reliable(self.threshold) else None

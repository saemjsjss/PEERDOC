"""Building blocks shared by every extracted document."""

from __future__ import annotations

from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")

# Placeholder until calibrated against real PaddleOCR-VL output on the sample set.
DEFAULT_CONFIDENCE_THRESHOLD = 0.90


class Frozen(BaseModel):
    """Immutable model that rejects unknown fields, so OCR output can't smuggle in typos."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Extracted(Frozen, Generic[T]):
    """One value read by OCR: what was read, how sure the reader was, and where it was."""

    value: T | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_page: int | None = Field(default=None, ge=1)

    @property
    def found(self) -> bool:
        return self.value is not None

    def is_reliable(self, threshold: float) -> bool:
        return self.found and self.confidence >= threshold


class Person(str, Enum):
    """The three people a case is about. Doubles as the affidavit 'subject'."""

    STUDENT = "STUDENT"
    FATHER = "FATHER"
    MOTHER = "MOTHER"

    @property
    def ref_label(self) -> str:
        return {"STUDENT": "StudentRef", "FATHER": "FatherRef", "MOTHER": "MotherRef"}[self.value]


class Language(str, Enum):
    ENGLISH = "ENGLISH"
    BANGLA = "BANGLA"
    MIXED = "MIXED"


class NotaryInfo(Frozen):
    """What Pass 1 found about notarisation on a document's pages."""

    notary_text_present: Extracted[bool] = Field(
        default_factory=Extracted[bool],
        description="'Notary Public' or 'Advocate' text found",
    )
    stamp_present: Extracted[bool] = Field(
        default_factory=Extracted[bool],
        description="A notary/advocate stamp or seal found",
    )

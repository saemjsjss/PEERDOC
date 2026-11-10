"""The complete input to the rules engine for one student."""

from __future__ import annotations

from datetime import date
from typing import Annotated, TypeVar, Union

from pydantic import Field

from .common import Frozen
from .documents import (
    AcademicCertificate,
    AcademicTranscript,
    Affidavit,
    BankSolvency,
    BankStatement,
    BirthCertificate,
    DocumentBase,
    EApostille,
    FamilyRelationshipCertificate,
    IncomeTaxAcknowledgement,
    IncomeTaxCertificate,
    IncomeTaxChallan,
    NationalId,
    Passport,
    Photo,
    TinCertificate,
    TradeLicense,
)

Document = Annotated[
    Union[
        Passport,
        Photo,
        BirthCertificate,
        NationalId,
        FamilyRelationshipCertificate,
        Affidavit,
        BankSolvency,
        BankStatement,
        TradeLicense,
        TinCertificate,
        IncomeTaxChallan,
        IncomeTaxAcknowledgement,
        IncomeTaxCertificate,
        EApostille,
        AcademicCertificate,
        AcademicTranscript,
    ],
    Field(discriminator="kind"),
]

D = TypeVar("D", bound=DocumentBase)


class CaseFile(Frozen):
    case_id: str = Field(min_length=1)
    evaluation_date: date = Field(
        description="'Current date' for every date rule; injected so verdicts are reproducible"
    )
    documents: tuple[Document, ...] = ()

    def of_kind(self, cls: type[D]) -> list[D]:
        return [d for d in self.documents if isinstance(d, cls)]

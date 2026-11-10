"""Typed documents produced by Pass 1 (OCR + content-based classification).

Each model holds only the fields Rulebook v2.5 needs. Pass 1 groups related pages
(e.g. an NID card and its notarised English translation) into one document.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import Field

from .common import Extracted, Frozen, Language, NotaryInfo, Person


def _str() -> Extracted[str]:
    return Extracted[str]()


def _date() -> Extracted[date]:
    return Extracted[date]()


def _bool() -> Extracted[bool]:
    return Extracted[bool]()


def _money() -> Extracted[Decimal]:
    return Extracted[Decimal]()


def _lang() -> Extracted[Language]:
    return Extracted[Language]()


class DocumentBase(Frozen):
    doc_id: str = Field(min_length=1)
    pages: tuple[int, ...] = Field(default=(), description="1-based page numbers in the upload")


# --- Identity -----------------------------------------------------------------


class Passport(DocumentBase):
    kind: Literal["passport"] = "passport"
    passport_number: Extracted[str] = Field(default_factory=_str)
    surname: Extracted[str] = Field(default_factory=_str)
    given_names: Extracted[str] = Field(default_factory=_str)
    mrz_surname: Extracted[str] = Field(default_factory=_str)
    mrz_given_names: Extracted[str] = Field(default_factory=_str)
    date_of_birth: Extracted[date] = Field(default_factory=_date)
    date_of_expiry: Extracted[date] = Field(default_factory=_date)
    father_name: Extracted[str] = Field(default_factory=_str)
    mother_name: Extracted[str] = Field(default_factory=_str)


class Photo(DocumentBase):
    kind: Literal["photo"] = "photo"


class BirthCertificate(DocumentBase):
    kind: Literal["birth_certificate"] = "birth_certificate"
    registration_number: Extracted[str] = Field(default_factory=_str)
    name: Extracted[str] = Field(default_factory=_str)
    date_of_birth: Extracted[date] = Field(default_factory=_date)
    father_name: Extracted[str] = Field(default_factory=_str)
    mother_name: Extracted[str] = Field(default_factory=_str)
    language: Extracted[Language] = Field(default_factory=_lang)
    has_english_translation: Extracted[bool] = Field(default_factory=_bool)
    notary: NotaryInfo | None = None


class NidVariant(str, Enum):
    DIGITAL = "DIGITAL"  # has MRZ (I<BGD)
    OLD = "OLD"  # no MRZ


class NationalId(DocumentBase):
    kind: Literal["nid"] = "nid"
    variant: NidVariant
    cardholder_name: Extracted[str] = Field(default_factory=_str)
    date_of_birth: Extracted[date] = Field(default_factory=_date)
    number_on_card: Extracted[str] = Field(default_factory=_str)
    number_on_translation: Extracted[str] = Field(default_factory=_str)
    has_english_translation: Extracted[bool] = Field(default_factory=_bool)
    notary: NotaryInfo | None = None


class DeathCertificate(DocumentBase):
    """Replaces a deceased parent's NID (REQ-08 / REQ-09)."""

    kind: Literal["death_certificate"] = "death_certificate"
    registration_number: Extracted[str] = Field(default_factory=_str)
    deceased_name: Extracted[str] = Field(default_factory=_str)
    date_of_death: Extracted[date] = Field(default_factory=_date)
    language: Extracted[Language] = Field(default_factory=_lang)
    has_english_translation: Extracted[bool] = Field(default_factory=_bool)
    notary: NotaryInfo | None = None


class FrcMember(Frozen):
    """One row of the FRC members table. `name` is the raw cell, e.g. 'X S/O: Y & Z'."""

    name: Extracted[str] = Field(default_factory=_str)
    relation: Extracted[str] = Field(default_factory=_str)
    date_of_birth: Extracted[date] = Field(default_factory=_date)


class FamilyRelationshipCertificate(DocumentBase):
    kind: Literal["frc"] = "frc"
    issuer_text: Extracted[str] = Field(
        default_factory=_str, description="Header/issuer block text, e.g. '03 NO. CHANDLA UNION PARISHAD'"
    )
    members: tuple[FrcMember, ...] = ()
    issue_date: Extracted[date] = Field(default_factory=_date)
    registration_date: Extracted[date] = Field(default_factory=_date)
    notary: NotaryInfo | None = None


class AffidavitEntry(Frozen):
    """One 'existing name' vs 'different name' declaration for one person."""

    person: Person
    existing_name: Extracted[str] = Field(default_factory=_str)
    different_name: Extracted[str] = Field(default_factory=_str)


class Affidavit(DocumentBase):
    kind: Literal["affidavit"] = "affidavit"
    deponent_name: Extracted[str] = Field(default_factory=_str)
    states_same_person: Extracted[bool] = Field(default_factory=_bool)
    entries: tuple[AffidavitEntry, ...] = ()
    notary: NotaryInfo | None = None


# --- Financial ----------------------------------------------------------------


class BankSolvency(DocumentBase):
    kind: Literal["bank_solvency"] = "bank_solvency"
    account_holder: Extracted[str] = Field(default_factory=_str)
    account_number: Extracted[str] = Field(default_factory=_str)
    letter_date: Extracted[date] = Field(default_factory=_date)


class BankStatement(DocumentBase):
    kind: Literal["bank_statement"] = "bank_statement"
    account_holder: Extracted[str] = Field(default_factory=_str)
    account_number: Extracted[str] = Field(default_factory=_str)
    statement_date: Extracted[date] = Field(
        default_factory=_date, description="Generation / 'As on' / print date"
    )


class TradeLicense(DocumentBase):
    kind: Literal["trade_license"] = "trade_license"
    license_number: Extracted[str] = Field(default_factory=_str)
    owner_name: Extracted[str] = Field(default_factory=_str)
    fiscal_year: Extracted[str] = Field(default_factory=_str, description="e.g. '2026-2027'")
    language: Extracted[Language] = Field(default_factory=_lang)
    has_english_translation: Extracted[bool] = Field(default_factory=_bool)
    notary: NotaryInfo | None = None


class EmploymentCertificate(DocumentBase):
    """Alternative to the Trade License (REQ-06): a parent's employer confirms employment."""

    kind: Literal["employment_certificate"] = "employment_certificate"
    employee_name: Extracted[str] = Field(default_factory=_str)
    employer_name: Extracted[str] = Field(default_factory=_str)
    designation: Extracted[str] = Field(default_factory=_str)
    issue_date: Extracted[date] = Field(default_factory=_date, description="Date the letter was issued")
    currently_employed: Extracted[bool] = Field(
        default_factory=_bool,
        description="Letter says the person IS employed now (not an experience/release letter)",
    )
    language: Extracted[Language] = Field(default_factory=_lang)
    has_english_translation: Extracted[bool] = Field(default_factory=_bool)
    notary: NotaryInfo | None = None


class TinCertificate(DocumentBase):
    kind: Literal["tin_certificate"] = "tin_certificate"
    taxpayer_name: Extracted[str] = Field(default_factory=_str)
    tin_printed: Extracted[str] = Field(default_factory=_str)
    # ZXing decoding is deterministic: it either decodes or it doesn't.
    qr_decoded: bool = False
    tin_from_qr: str | None = None


class IncomeTaxChallan(DocumentBase):
    kind: Literal["tax_challan"] = "tax_challan"
    challan_number: Extracted[str] = Field(default_factory=_str)
    printed_amount: Extracted[Decimal] = Field(default_factory=_money)


class IncomeTaxAcknowledgement(DocumentBase):
    kind: Literal["tax_acknowledgement"] = "tax_acknowledgement"
    total_tax_paid: Extracted[Decimal] = Field(default_factory=_money)
    total_income: Extracted[Decimal] = Field(default_factory=_money)


class IncomeTaxCertificate(DocumentBase):
    kind: Literal["tax_certificate"] = "tax_certificate"
    taxpayer_name: Extracted[str] = Field(default_factory=_str)


# --- Academic -----------------------------------------------------------------


class AcademicLevel(str, Enum):
    SSC = "SSC"
    HSC = "HSC"
    DAKHIL = "DAKHIL"
    ALIM = "ALIM"
    DIPLOMA = "DIPLOMA"
    BACHELOR = "BACHELOR"
    MASTERS = "MASTERS"
    OTHER = "OTHER"


class EApostille(DocumentBase):
    kind: Literal["e_apostille"] = "e_apostille"
    qr_decoded: bool = False
    qr_url: str | None = None


class AcademicCertificate(DocumentBase):
    kind: Literal["academic_certificate"] = "academic_certificate"
    level: Extracted[AcademicLevel] = Field(default_factory=Extracted[AcademicLevel])
    student_name: Extracted[str] = Field(default_factory=_str)
    date_of_birth: Extracted[date] = Field(default_factory=_date)


class AcademicTranscript(DocumentBase):
    kind: Literal["academic_transcript"] = "academic_transcript"
    level: Extracted[AcademicLevel] = Field(default_factory=Extracted[AcademicLevel])
    student_name: Extracted[str] = Field(default_factory=_str)

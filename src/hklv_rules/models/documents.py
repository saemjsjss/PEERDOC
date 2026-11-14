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


class OnlineStatus(str, Enum):
    """Result of checking a document against an official website."""

    VERIFIED = "VERIFIED"  # the site confirms the record
    NOT_FOUND = "NOT_FOUND"  # the site says there is no such record
    UNAVAILABLE = "UNAVAILABLE"  # the check was attempted but the site/internet failed
    NOT_RUN = "NOT_RUN"  # online checks were not enabled for this run


class OnlineCheck(Frozen):
    """What an online verification step found. Filled in outside the rules engine (which
    never does I/O); the rules only interpret it."""

    status: OnlineStatus
    detail: str = ""
    amount: Decimal | None = Field(default=None, description="Amount the website shows (challan)")
    # RULES-v10, e-Apostille register: which number was looked up, and what the register holds
    number: str | None = Field(default=None, description="Apostille number looked up")
    number_source: Literal["qr", "printed"] | None = None
    register_date: date | None = Field(default=None, description="Apostille date in the register")
    register_pages: tuple[RegisterPage, ...] = Field(default=(), description="The register's own copy, read by OCR")
    register_note: str = Field(default="", description="Why the register copy could not be read, if so")


class DocumentBase(Frozen):
    doc_id: str = Field(min_length=1)
    pages: tuple[int, ...] = Field(default=(), description="1-based page numbers in the upload")
    notary_dates: tuple[Extracted[date], ...] = Field(default=(), description="Dates on the notary's stamp/attestation")
    translation_dates: tuple[Extracted[date], ...] = Field(default=(), description="Dates by the translator's signature")


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
    printed_date_of_expiry: Extracted[date] = Field(
        default_factory=_date,
        description=(
            "Expiry as printed on the data page ('Date of Expiry'), read even when an MRZ exists. "
            "date_of_expiry holds the check-digit-verified MRZ value when there is an MRZ; "
            "PASSPORT-01 compares the two (rulebook 4.1: MRZ and print mismatch -> FLAG)."
        ),
    )
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
    late_names: tuple[Extracted[str], ...] = Field(
        default=(), description="Parents the text names as deceased: 'son of Late Md Abdur Razzak'"
    )


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
    usd_amount: Extracted[str] = Field(default_factory=_str, description="An amount in US dollars")
    bdt_amount: Extracted[str] = Field(default_factory=_str, description="An amount in taka")


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
    valid_until: Extracted[date] = Field(default_factory=_date, description="'Valid up to 30 June 2027'")
    issue_date: Extracted[date] = Field(default_factory=_date)
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
    online: OnlineCheck | None = Field(default=None, description="challanverification.finance.gov.bd result")


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


class RegisterPage(Frozen):
    """One document page as the e-Apostille register holds it (RULES-v10), read by OCR."""

    title: str = Field(description="The register's title, e.g. 'HSC Transcript (ForAttestation)*'")
    level: Extracted[AcademicLevel] = Field(default_factory=Extracted[AcademicLevel])
    student_name: Extracted[str] = Field(default_factory=_str)
    registration_number: Extracted[str] = Field(default_factory=_str)

    @property
    def is_transcript(self) -> bool | None:
        t = self.title.upper()
        if "TRANSCRIPT" in t or "MARK" in t or "GRADE" in t:
            return True
        return False if "CERTIFICATE" in t else None


OnlineCheck.model_rebuild()


class EApostille(DocumentBase):
    kind: Literal["e_apostille"] = "e_apostille"
    qr_decoded: bool = False
    qr_url: str | None = None
    printed_number: Extracted[str] = Field(default_factory=_str, description="Field 8 'No' printed on the page (RULES-v10)")
    online: OnlineCheck | None = Field(default=None, description="Result of opening the QR link")


class AcademicCertificate(DocumentBase):
    kind: Literal["academic_certificate"] = "academic_certificate"
    level: Extracted[AcademicLevel] = Field(default_factory=Extracted[AcademicLevel])
    student_name: Extracted[str] = Field(default_factory=_str)
    date_of_birth: Extracted[date] = Field(default_factory=_date)
    registration_number: Extracted[str] = Field(default_factory=_str, description="Board registration no., without the session")
    notary: NotaryInfo | None = None


class AcademicTranscript(DocumentBase):
    kind: Literal["academic_transcript"] = "academic_transcript"
    level: Extracted[AcademicLevel] = Field(default_factory=Extracted[AcademicLevel])
    student_name: Extracted[str] = Field(default_factory=_str)
    registration_number: Extracted[str] = Field(default_factory=_str, description="Board registration no., without the session")
    notary: NotaryInfo | None = None


# --- Language test (optional) ---------------------------------------------------


class LanguageTestKind(str, Enum):
    IELTS = "IELTS"
    TOPIK = "TOPIK"


class LanguageTest(DocumentBase):
    """IELTS Test Report Form or TOPIK certificate (section 4.10; optional document)."""

    kind: Literal["language_test"] = "language_test"
    test: Extracted[LanguageTestKind] = Field(default_factory=Extracted[LanguageTestKind])
    candidate_name: Extracted[str] = Field(default_factory=_str)
    date_of_birth: Extracted[date] = Field(default_factory=_date)
    test_date: Extracted[date] = Field(default_factory=_date, description="Test date (IELTS) / issue date (TOPIK)")

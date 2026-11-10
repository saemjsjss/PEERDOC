"""Test data builders. All people here are fictional.

Default family:
    Student  TANVIR AHMED     (passport printed + MRZ)
    Father   MD. KAMAL UDDIN  (birth certificate)
    Mother   RINA BEGUM       (birth certificate)
"""

from __future__ import annotations

from datetime import date

from hklv_rules.context import EvaluationContext
from hklv_rules.models import (
    Affidavit,
    AffidavitEntry,
    BankSolvency,
    BankStatement,
    BirthCertificate,
    CaseFile,
    DeathCertificate,
    EmploymentCertificate,
    Extracted,
    FamilyRelationshipCertificate,
    FrcMember,
    NationalId,
    NidVariant,
    NotaryInfo,
    Language,
    Passport,
    Person,
    Photo,
    TinCertificate,
    TradeLicense,
)

EVAL_DATE = date(2026, 11, 10)
STUDENT = "TANVIR AHMED"
FATHER = "MD. KAMAL UDDIN"
MOTHER = "RINA BEGUM"
HIGH, LOW = 0.99, 0.40


def ex(value, confidence: float = HIGH, page: int = 1) -> Extracted:
    return Extracted(value=value, confidence=confidence, source_page=page)


def notarised(text: bool = True, stamp: bool = True, confidence: float = HIGH) -> NotaryInfo:
    return NotaryInfo(notary_text_present=ex(text, confidence), stamp_present=ex(stamp, confidence))


def passport(
    given: str = "TANVIR",
    surname: str = "AHMED",
    mrz_given: str | None = None,
    mrz_surname: str | None = None,
    father: str | None = None,
    mother: str | None = None,
) -> Passport:
    return Passport(
        doc_id="passport",
        given_names=ex(given),
        surname=ex(surname),
        mrz_given_names=ex(mrz_given if mrz_given is not None else given),
        mrz_surname=ex(mrz_surname if mrz_surname is not None else surname),
        father_name=ex(father) if father else Extracted[str](),
        mother_name=ex(mother) if mother else Extracted[str](),
    )


def birth_certificate(father: str = FATHER, mother: str = MOTHER, confidence: float = HIGH) -> BirthCertificate:
    return BirthCertificate(
        doc_id="birth",
        name=ex(STUDENT),
        father_name=ex(father, confidence),
        mother_name=ex(mother, confidence),
    )


def tin(name: str, confidence: float = HIGH, doc_id: str = "tin") -> TinCertificate:
    return TinCertificate(doc_id=doc_id, taxpayer_name=ex(name, confidence))


def trade(name: str, confidence: float = HIGH, doc_id: str = "trade") -> TradeLicense:
    return TradeLicense(doc_id=doc_id, owner_name=ex(name, confidence))


def nid(doc_id: str, name: str, confidence: float = HIGH, variant: NidVariant = NidVariant.DIGITAL) -> NationalId:
    return NationalId(doc_id=doc_id, variant=variant, cardholder_name=ex(name, confidence))


def affidavit(
    *entries: tuple[Person, str, str],
    deponent: str = STUDENT,
    same_person: bool = True,
    notary: NotaryInfo | None = None,
    doc_id: str = "affidavit",
) -> Affidavit:
    return Affidavit(
        doc_id=doc_id,
        deponent_name=ex(deponent),
        states_same_person=ex(same_person),
        entries=tuple(AffidavitEntry(person=p, existing_name=ex(a), different_name=ex(b)) for p, a, b in entries),
        notary=notary if notary is not None else notarised(),
    )


def member(name: str, relation: str, confidence: float = HIGH) -> FrcMember:
    return FrcMember(name=ex(name), relation=ex(relation, confidence))


def default_members() -> tuple[FrcMember, ...]:
    return (
        member(f"{STUDENT} S/O: KAMAL UDDIN & RINA BEGUM", "SELF"),
        member("MOHAMMAD KAMAL UDDIN", "FATHER"),
        member(MOTHER, "MOTHER"),
        member("SADIA AHMED", "SISTER"),
    )


_DEFAULT = object()


def frc(
    members: tuple[FrcMember, ...] | None = None,
    issuer: str = "03 NO. CHANDLA UNION PARISHAD",
    issue_date: date | None = date(2026, 9, 9),
    registration_date: date | None = None,
    notary=_DEFAULT,
    doc_id: str = "frc",
) -> FamilyRelationshipCertificate:
    return FamilyRelationshipCertificate(
        doc_id=doc_id,
        issuer_text=ex(issuer),
        members=members if members is not None else default_members(),
        issue_date=ex(issue_date) if issue_date else Extracted[date](),
        registration_date=ex(registration_date) if registration_date else Extracted[date](),
        notary=notarised() if notary is _DEFAULT else notary,
    )


def context(*docs, with_identity_docs: bool = True, evaluation_date: date = EVAL_DATE) -> EvaluationContext:
    base = [passport(), birth_certificate()] if with_identity_docs else []
    case = CaseFile(case_id="test", evaluation_date=evaluation_date, documents=tuple(base) + docs)
    return EvaluationContext.build(case)


def by_rule(results) -> dict:
    out = {}
    for r in results:
        assert r.rule_id not in out, f"duplicate {r.rule_id}"
        out[r.rule_id] = r
    return out


def employment(
    name: str = FATHER,
    issue_date: date | None = date(2026, 10, 1),
    currently_employed: bool | None = True,
    language: Language = Language.ENGLISH,
    translated: bool | None = None,
    notary=_DEFAULT,
    confidence: float = HIGH,
    status_confidence: float = HIGH,
    doc_id: str = "employment",
) -> EmploymentCertificate:
    return EmploymentCertificate(
        doc_id=doc_id,
        employee_name=ex(name, confidence),
        employer_name=ex("NORTHWIND TEXTILES LTD"),
        designation=ex("SENIOR ACCOUNTANT"),
        issue_date=ex(issue_date) if issue_date else Extracted[date](),
        currently_employed=(
            ex(currently_employed, status_confidence) if currently_employed is not None else Extracted[bool]()
        ),
        language=ex(language),
        has_english_translation=ex(translated) if translated is not None else Extracted[bool](),
        notary=notarised() if notary is _DEFAULT else notary,
    )


def death(
    name: str = FATHER,
    date_of_death: date | None = date(2021, 3, 14),
    language: Language = Language.BANGLA,
    translated: bool | None = True,
    notary=_DEFAULT,
    confidence: float = HIGH,
    date_confidence: float = HIGH,
    doc_id: str = "death",
) -> DeathCertificate:
    return DeathCertificate(
        doc_id=doc_id,
        deceased_name=ex(name, confidence),
        date_of_death=ex(date_of_death, date_confidence) if date_of_death else Extracted[date](),
        language=ex(language),
        has_english_translation=ex(translated) if translated is not None else Extracted[bool](),
        notary=notarised() if notary is _DEFAULT else notary,
    )


def complete_case_documents() -> list:
    """A full, valid fictional submission (everything section 3 requires)."""
    return [
        Photo(doc_id="photo"),
        frc(),
        BankSolvency(doc_id="solvency", account_holder=ex(FATHER), account_number=ex("0123456789")),
        BankStatement(doc_id="statement", account_holder=ex(FATHER), account_number=ex("0123456789")),
        trade(FATHER),
        tin(FATHER),
        nid("n-father", FATHER),
        nid("n-mother", MOTHER),
    ]


def case_file(*docs, evaluation_date: date = EVAL_DATE) -> CaseFile:
    """CaseFile with the default passport + birth certificate prepended."""
    return CaseFile(
        case_id="test",
        evaluation_date=evaluation_date,
        documents=(passport(), birth_certificate(), *docs),
    )

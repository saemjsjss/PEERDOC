"""Test data builders. All people here are fictional.

Default family:
    Student  TANVIR AHMED     (passport printed + MRZ), born 15 March 2001
    Father   MD. KAMAL UDDIN  (birth certificate)
    Mother   RINA BEGUM       (birth certificate)

Every default document is complete and valid on EVAL_DATE, so `complete_case_documents()`
passes every rule; tests change one thing at a time.
"""

from __future__ import annotations

from datetime import date

from hklv_rules.context import EvaluationContext
from hklv_rules.models import (
    AcademicCertificate,
    AcademicLevel,
    AcademicTranscript,
    Affidavit,
    AffidavitEntry,
    BankSolvency,
    BankStatement,
    BirthCertificate,
    CaseFile,
    DeathCertificate,
    EApostille,
    EmploymentCertificate,
    Extracted,
    FamilyRelationshipCertificate,
    FrcMember,
    NationalId,
    NidVariant,
    NotaryInfo,
    Language,
    OnlineCheck,
    OnlineStatus,
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
_DEFAULT = object()
STUDENT_DOB = date(2001, 3, 15)
STUDENT_BRN = "20012691234567890"  # starts with the birth year (BIRTH-04)
PASSPORT_EXPIRY = date(2031, 1, 1)
NID_NUMBER = "5551234567"
TIN_NUMBER = "123456789012"
ACCOUNT_NUMBER = "0123456789"
BANK_DATE = date(2026, 10, 20)
APOSTILLE_URL = "https://apostille.mygov.bd/application-details/100000000001"


def ex(value, confidence: float = HIGH, page: int = 1) -> Extracted:
    return Extracted(value=value, confidence=confidence, source_page=page)


def notarised(text: bool = True, stamp: bool = True, confidence: float = HIGH) -> NotaryInfo:
    return NotaryInfo(notary_text_present=ex(text, confidence), stamp_present=ex(stamp, confidence))


def _opt(value, confidence: float = HIGH) -> Extracted:
    return ex(value, confidence) if value is not None else Extracted()


def passport(
    given: str = "TANVIR",
    surname: str = "AHMED",
    mrz_given: str | None = None,
    mrz_surname: str | None = None,
    father: str | None = None,
    mother: str | None = None,
    dob: date | None = STUDENT_DOB,
    expiry: date | None = PASSPORT_EXPIRY,
    date_confidence: float = HIGH,
    doc_id: str = "passport",
    printed_expiry=_DEFAULT,
) -> Passport:
    """`printed_expiry`: the printed 'Date of Expiry' (default: same as the MRZ `expiry`)."""
    printed = expiry if printed_expiry is _DEFAULT else printed_expiry
    return Passport(
        doc_id=doc_id,
        passport_number=ex("K12345678"),
        given_names=ex(given),
        surname=ex(surname),
        mrz_given_names=ex(mrz_given if mrz_given is not None else given),
        mrz_surname=ex(mrz_surname if mrz_surname is not None else surname),
        date_of_birth=_opt(dob, date_confidence),
        date_of_expiry=_opt(expiry, date_confidence),
        printed_date_of_expiry=_opt(printed, date_confidence),
        father_name=ex(father) if father else Extracted[str](),
        mother_name=ex(mother) if mother else Extracted[str](),
    )


def birth_certificate(
    father: str = FATHER,
    mother: str = MOTHER,
    confidence: float = HIGH,
    dob: date | None = STUDENT_DOB,
    brn: str | None = STUDENT_BRN,
    language: Language = Language.ENGLISH,
    translated: bool | None = None,
    notary=_DEFAULT,
    field_confidence: float = HIGH,
    doc_id: str = "birth",
    name: str | None = STUDENT,
) -> BirthCertificate:
    return BirthCertificate(
        doc_id=doc_id,
        registration_number=_opt(brn, field_confidence),
        name=_opt(name, confidence),
        date_of_birth=_opt(dob, field_confidence),
        father_name=ex(father, confidence),
        mother_name=ex(mother, confidence),
        language=ex(language),
        has_english_translation=_opt(translated),
        notary=notarised() if notary is _DEFAULT else notary,
    )


def tin(
    name: str,
    confidence: float = HIGH,
    doc_id: str = "tin",
    printed: str | None = TIN_NUMBER,
    qr: str | None = TIN_NUMBER,
    qr_decoded: bool | None = None,
) -> TinCertificate:
    return TinCertificate(
        doc_id=doc_id,
        taxpayer_name=ex(name, confidence),
        tin_printed=_opt(printed),
        qr_decoded=(qr is not None) if qr_decoded is None else qr_decoded,
        tin_from_qr=qr,
    )


def trade(
    name: str,
    confidence: float = HIGH,
    doc_id: str = "trade",
    fiscal_year: str | None = "2026-2027",
    language: Language = Language.ENGLISH,
    translated: bool | None = None,
    notary=_DEFAULT,
) -> TradeLicense:
    return TradeLicense(
        doc_id=doc_id,
        license_number=ex("TRAD/DNCC/012345/2026"),
        owner_name=ex(name, confidence),
        fiscal_year=_opt(fiscal_year),
        language=ex(language),
        has_english_translation=_opt(translated),
        notary=notarised() if notary is _DEFAULT else notary,
    )


def nid(
    doc_id: str,
    name: str,
    confidence: float = HIGH,
    variant: NidVariant = NidVariant.DIGITAL,
    number: str | None = NID_NUMBER,
    translation_number: str | None = None,
    translated: bool | None = True,
    notary=_DEFAULT,
    number_confidence: float = HIGH,
) -> NationalId:
    """Defaults: card and translation numbers match, translated, notarised."""
    return NationalId(
        doc_id=doc_id,
        variant=variant,
        cardholder_name=ex(name, confidence),
        number_on_card=_opt(number, number_confidence),
        number_on_translation=_opt(translation_number if translation_number is not None else number, number_confidence),
        has_english_translation=_opt(translated),
        notary=notarised() if notary is _DEFAULT else notary,
    )


def bank_solvency(
    holder: str = FATHER,
    account: str | None = ACCOUNT_NUMBER,
    letter_date: date | None = BANK_DATE,
    confidence: float = HIGH,
    doc_id: str = "solvency",
    usd: str | None = "USD 19,338.09",
    bdt: str | None = "BDT 2,407,592.52",
) -> BankSolvency:
    return BankSolvency(
        doc_id=doc_id,
        account_holder=ex(holder, confidence),
        account_number=_opt(account, confidence),
        letter_date=_opt(letter_date, confidence),
        usd_amount=_opt(usd, confidence),
        bdt_amount=_opt(bdt, confidence),
    )


def bank_statement(
    holder: str = FATHER,
    account: str | None = ACCOUNT_NUMBER,
    statement_date: date | None = BANK_DATE,
    confidence: float = HIGH,
    doc_id: str = "statement",
) -> BankStatement:
    return BankStatement(
        doc_id=doc_id,
        account_holder=ex(holder, confidence),
        account_number=_opt(account, confidence),
        statement_date=_opt(statement_date, confidence),
    )


def apostille(
    doc_id: str = "apostille-1",
    page: int = 20,
    url: str | None = APOSTILLE_URL,
    online: OnlineStatus | None = OnlineStatus.VERIFIED,
) -> EApostille:
    return EApostille(
        doc_id=doc_id,
        pages=(page,),
        qr_decoded=url is not None,
        qr_url=url,
        online=OnlineCheck(status=online) if online is not None else None,
    )


def academic_certificate(
    level: AcademicLevel = AcademicLevel.SSC,
    name: str = STUDENT,
    dob: date | None = STUDENT_DOB,
    page: int = 21,
    doc_id: str | None = None,
    confidence: float = HIGH,
) -> AcademicCertificate:
    return AcademicCertificate(
        doc_id=doc_id or f"cert-{level.value.lower()}",
        pages=(page,),
        level=ex(level, confidence),
        student_name=ex(name, confidence),
        date_of_birth=_opt(dob, confidence),
        notary=notarised(),
    )


def academic_transcript(
    level: AcademicLevel = AcademicLevel.SSC,
    name: str = STUDENT,
    page: int = 23,
    doc_id: str | None = None,
    confidence: float = HIGH,
) -> AcademicTranscript:
    return AcademicTranscript(
        doc_id=doc_id or f"transcript-{level.value.lower()}",
        pages=(page,),
        level=ex(level, confidence),
        student_name=ex(name, confidence),
        notary=notarised(),
    )


def academic_set(first_page: int = 20, levels=(AcademicLevel.SSC, AcademicLevel.HSC)) -> list:
    """Each certificate and transcript preceded by its own verified e-Apostille page:
    apostille, SSC certificate, apostille, SSC transcript, apostille, HSC certificate, ...
    Only SSC/Dakhil certificates carry a date of birth (ACAD-04 checks those)."""
    docs, page = [], first_page
    for level in levels:
        docs.append(apostille(doc_id=f"apostille-{page}", page=page))
        has_dob = level in (AcademicLevel.SSC, AcademicLevel.DAKHIL)
        docs.append(academic_certificate(level, page=page + 1, dob=STUDENT_DOB if has_dob else None))
        docs.append(apostille(doc_id=f"apostille-{page + 2}", page=page + 2))
        docs.append(academic_transcript(level, page=page + 3))
        page += 4
    return docs


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
    """A full, valid fictional submission (section 3 requirements plus SSC + HSC academics).
    Combined with the default passport and birth certificate it passes every rule."""
    return [
        Photo(doc_id="photo"),
        frc(),
        bank_solvency(),
        bank_statement(),
        trade(FATHER),
        tin(FATHER),
        nid("n-father", FATHER, number="4441234567"),
        nid("n-mother", MOTHER, number="6661234567"),
        *academic_set(),
    ]


def case_file(*docs, evaluation_date: date = EVAL_DATE) -> CaseFile:
    """CaseFile with the default passport + birth certificate prepended."""
    return CaseFile(
        case_id="test",
        evaluation_date=evaluation_date,
        documents=(passport(), birth_certificate(), *docs),
    )

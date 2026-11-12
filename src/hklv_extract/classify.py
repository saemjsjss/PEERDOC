"""Content-based page classification (Rulebook section 1.1). File names are never used.

Each page gets one kind. Signatures are checked from the most specific to the most
generic, because generic words recur: every notarised translation says "Notary Public",
and university letters also say "To Whom It May Concern".
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict

from hklv_ocr.reading import PageReading

from .common_fields import TRANSLATION_RE
from .mrz import MrzResult, find_mrz
from .text import reading_order


class PageKind(str, Enum):
    PASSPORT = "passport"
    PHOTO = "photo"
    BIRTH_CERTIFICATE = "birth_certificate"
    NID = "nid"
    DEATH_CERTIFICATE = "death_certificate"
    FRC = "frc"
    BANK_SOLVENCY = "bank_solvency"
    BANK_STATEMENT = "bank_statement"
    TRADE_LICENSE = "trade_license"
    EMPLOYMENT_CERTIFICATE = "employment_certificate"
    TIN_CERTIFICATE = "tin_certificate"
    TAX_CHALLAN = "tax_challan"
    TAX_ACKNOWLEDGEMENT = "tax_acknowledgement"
    TAX_CERTIFICATE = "tax_certificate"
    E_APOSTILLE = "e_apostille"
    ACADEMIC_CERTIFICATE = "academic_certificate"
    ACADEMIC_TRANSCRIPT = "academic_transcript"
    LANGUAGE_TEST = "language_test"
    AFFIDAVIT = "affidavit"
    IGNORED = "ignored"  # IGNORE-01: matches no signature


class PageClass(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    page_no: int
    kind: PageKind
    reason: str
    mrz: MrzResult | None = None


def _rx(*patterns: str) -> re.Pattern[str]:
    return re.compile("|".join(patterns), re.IGNORECASE)


SIG = {
    "passport": _rx(r"\bPASSPORT\b", r"পাসপোর্ট"),
    "apostille": _rx(r"\bE-?\s?APOSTILLE\b", r"\bAPOSTILLE\b", r"Convention de La Haye"),
    "nid": _rx(r"NATIONAL\s*ID(?:ENTITY)?\s*CARD", r"\bNID\s*CARD\b", r"জাতীয়\s*পরিচয়\s*পত্র"),
    # A bare 'NID No' is quoted by bank and employer letters too: the weakest NID evidence.
    "nid_number": _rx(r"\bNID\s*(?:NO|NUMBER)\b"),
    "birth": _rx(r"BIRTH\s*REGISTRATION\s*(?:NUMBER|NO)", r"\bBDRIS\b", r"জন্ম\s*নিবন্ধন"),
    # Older City Corporation / Pourashava certificates (BDR Form-3, titled "Birth Registration
    # Certificate" in a decorative font OCR often garbles): see OLD_STYLE_BIRTH below.
    "birth_registrar": _rx(r"REGISTRAR\s*OF\s*BIRTH", r"BIRTH\s*(?:AND|&)\s*DEATH\s*REGISTRAR", r"\bBDR\s*FORM\b"),
    "date_of_birth": _rx(r"DATE\s*OF\s*BIRTH"),
    # Not plain "Death Registration": every BDRIS birth certificate is issued by the
    # "Registrar of Birth and Death".
    # The Bangla title sits in a decorative banner OCR can't read; its rows (date, cause and
    # place of death) are plain text. A Bangla death certificate also has an NID-number row.
    "death": _rx(
        r"DEATH\s*REGISTRATION\s*(?:NUMBER|NO)",
        r"DEATH\s*CERTIFICATE",
        r"DATE\s*OF\s*DEATH",
        r"মৃত্যু\s*নিবন্ধন\s*সনদ",
        r"মৃত্যুর?\s*(?:তারিখ|কারণ|স্থান)",
    ),
    # 'CERTIFI?CA?TE': some councils print 'CERTIFICTE'.
    "frc": _rx(r"FAMILY\s*RELATIONSHIP\s*CERTIFI?CA?TE", r"FAMILY\s*CERTIFI?CA?TE", r"ওয়ারিশ"),
    "frc_issuer": _rx(r"UNION\s*PARI?S(?:H|S)?AD", r"UNION\s*PORISHAD", r"POURASHAVA", r"PAURASHAVA", r"MUNICIPALITY", r"CITY\s*CORPORATION"),
    "challan": _rx(r"CHALLAN\s*FORM", r"চালান\s*ফরম", r"\bA-?CHALLAN\b", r"CHALLAN\s*HAS\s*BEEN\s*GENERATED"),
    "tax_ack": _rx(r"ACKNOWLEDGE?MENT\s*RECEIPT"),
    # TIN certificates also say "file the Return of Income": checked after TIN.
    "return_of_income": _rx(r"RETURN\s*OF\s*INCOME"),
    "tax_cert": _rx(r"INCOME\s*TAX\s*CERTIFICATE"),
    "tin": _rx(r"TAXPAYER'?S?\s*IDENTIFICATION\s*NUMBER", r"\bTIN\s*CERTIFICATE\b"),
    "nbr": _rx(r"NATIONAL\s*BOARD\s*OF\s*REVENUE", r"\bNBR\b"),
    # Also the licence's own verification QR (decoded by ZXing), e.g. ".../verify/trade_bn/...".
    # Union Parishads also title it "Professional Licence" (RULES-v3).
    "trade": _rx(
        r"TRADE\s*/?\s*(?:PROFESSION\s*)?LICEN[CS]E",
        r"PROFESSIONAL\s*LICEN[CS]E",
        r"NAME\s*OF\s*LICEN[CS]ES?\s*HOLDER",
        r"ট্রেড\s*লাইসেন্স",
        r"/verify/trade",
    ),
    "employment": _rx(r"EMPLOYMENT\s*CERTIFICATE", r"EXPERIENCE\s*CERTIFICATE", r"\bIS\s+(?:WORKING|EMPLOYED|SERVING)\b"),
    "solvency": _rx(r"\bSOLVENCY\b", r"ACCOUNT\s*HOLDER"),
    "to_whom": _rx(r"TO\s*WHOM\s*IT\s*MAY\s*CONCERN"),
    "bank": _rx(r"\bBANK\b", r"\bBRANCH\b"),
    "account": _rx(r"\bA/?C\b", r"\bACCOUNT\b"),
    "statement": _rx(r"STATEMENT\s*OF\s*ACCOUNT", r"ACCOUNT\s*STATEMENT", r"BANK\s*STATEMENT"),
    # Also the subject list: a notary stamp can cover the title. Not "Letter Grade":
    # certificates print the grading-scale legend too.
    "transcript": _rx(r"ACADEMIC\s*TRANSCRIPT", r"\bTRANSCRIPT\b", r"GRADE\s*SHEET", r"MARK\s*SHEET", r"NAME\s*OF\s*(?:THE\s*)?SUBJECTS?"),
    "acad_cert": _rx(r"CERTIFICATE\s*EXAMINATION", r"BOARD\s*OF\s*INTERMEDIATE", r"MADRASAH\s*EDUCATION\s*BOARD", r"TECHNICAL\s*EDUCATION\s*BOARD", r"\bUNIVERSITY\b"),
    "acad_award": _rx(r"\bPASSED\b", r"\bOBTAINED\b", r"\bDEGREE\b", r"\bG\.?P\.?A\b"),
    "language_test": _rx(r"\bIELTS\b", r"TEST\s*REPORT\s*FORM", r"\bTOPIK\b"),
    # Strong words only: "Notary Public" is on every notarised translation.
    "affidavit": _rx(r"\bAFFIDAVIT\b", r"SAME\s+PERSON", r"হলফনামা"),
}

_TX_HEADERS = ("DATE", "DEBIT", "CREDIT", "BALANCE")

# Fields only the birth register prints (BDR Form-3). "Place of Birth" is not one: cover
# letters, application forms and citizenship certificates print it too.
# Each with its value: an application form's blank office-use labels don't count.
_REGISTER_FIELDS = {
    "Date of Registration": re.compile(
        r"(?:DATE\s*OF\s*REGISTRATION|REGISTRATION\s*DATE)\s*[:：]?\s*\d{1,2}\s*[/\-.]\s*\d{1,2}\s*[/\-.]\s*\d{2,4}", re.IGNORECASE
    ),
    "Register No": re.compile(r"\bREGISTER\s*NO\.?\s*[:：]?\s*\d", re.IGNORECASE),
    "Order of Child": re.compile(r"ORDER\s*OF\s*CHILD\s*[:：]?\s*\d", re.IGNORECASE),
}
# Other documents that can carry the registrar's name (the Union Parishad chairman is also
# the birth and death registrar), a date of birth and a register serial.
_NOT_A_BIRTH_CERTIFICATE = re.compile(
    r"CITIZENSHIP|CHARACTER\s*CERTIFICATE|WARISH|\bHEIRS?\b|SUCCESSION|APPLICATION|APPLICANT|FOR\s*OFFICE\s*USE",
    re.IGNORECASE,
)
_BRN_LABEL = re.compile(r"\b(?:BR\s*(?:NUMBER|NO)|BRN)\b", re.IGNORECASE)
_BRN_DIGITS = re.compile(r"[^0-9]{0,15}\d(?:\s?\d){15,16}(?!\s?\d)")
_PARENT = re.compile(r"\b(?:FATHER|MOTHER|PARENT)", re.IGNORECASE)


def _has_own_brn(text: str) -> bool:
    """A real 16-17 digit number after "BR Number"/"BRN", and no "NID" right beside the
    label: a combined identity field ("NID/BRN", "BRN/NID", "NID or BRN", "NID No. (BRN)")
    is on citizenship and character certificates and cover letters, not on a birth
    certificate's own number."""
    return own_brn(text) is not None


def own_brn(text: str) -> str | None:
    """The page's own registration number: the digits after "BR Number"/"BRN"/"Birth
    Registration Number", not a parent's ("Father's BRN") or a combined NID field."""
    for m in _OWN_BRN_LABEL.finditer(text):
        beside = text[max(0, m.start() - 12) : m.end() + 12]
        if re.search(r"\bNID\b", beside, re.IGNORECASE) or _PARENT.search(text[max(0, m.start() - 25) : m.start()]):
            continue
        digits = _BRN_DIGITS.match(text, m.end())
        if digits:
            return re.sub(r"\D", "", digits.group(0))
    return None


_OWN_BRN_LABEL = re.compile(r"\b(?:BR\s*(?:NUMBER|NO)|BRN|BIRTH\s*REGISTRATION\s*(?:NUMBER|NO))\b", re.IGNORECASE)


OLD_STYLE_BIRTH = "birth registrar office + Date of Birth + "


def _has_transaction_table(page: PageReading) -> bool:
    """Bank statement: a table header row with Date, Debit, Credit and Balance."""
    words = {re.sub(r"[^A-Z]", "", ln.text.upper()) for ln in page.lines}
    text = page.block_text.upper()
    in_lines = all(any(h in w for w in words) for h in _TX_HEADERS)
    in_table = all(h in text for h in _TX_HEADERS) and "<TABLE" in text
    return in_lines or in_table


# the number may carry an OCR letter slip ('D60631')
_LICENCE_NUMBER = re.compile(r"TRADE\s*LICEN[CS]E\s*No\.?\s*[:\-]?\s*[A-Z0-9]*\d[A-Z0-9]*", re.IGNORECASE)


_LANGUAGE_FORM = re.compile(
    r"Candidate|Test[\s-]*taker|Date\s*of\s*Birth|Registration\s*No|Test\s*(?:Report|Date)|Score\s*Report",
    re.IGNORECASE,
)


def _only_translators_licence(text: str) -> bool:
    """Translation agencies print their own 'Trade Licence No. 136130' on every translated
    page (a translated NID, birth certificate, FRC ...). Such a page is a trade licence only
    if something else on it says so, e.g. the licence's own title."""
    return bool(TRANSLATION_RE.search(text)) and not SIG["trade"].search(_LICENCE_NUMBER.sub("", text))


def classify_page(page: PageReading, today: date) -> PageClass:
    lines_text = "\n".join(ln.text for ln in reading_order(page.lines))
    text = "\n".join([lines_text, page.block_text, *(b.text for b in page.barcodes)])
    has ={k: bool(rx.search(text)) for k, rx in SIG.items()}
    mrz = next(iter(find_mrz([ln.text for ln in reading_order(page.lines)], today)), None)

    def out(kind: PageKind, reason: str) -> PageClass:
        return PageClass(page_no=page.page_no, kind=kind, reason=reason, mrz=mrz)

    if page.from_image_file and len(page.lines) < 5:
        return out(PageKind.PHOTO, "image file with little or no text")
    # A photo saved as a PDF: no text, and the layout reader saw only a picture (a blank
    # scanned page has no picture block, so it is not taken for a photo).
    if not page.lines and page.blocks and all(b.label == "image" for b in page.blocks):
        return out(PageKind.PHOTO, "PDF page holding only a picture")
    if mrz is not None and mrz.format == "TD3" and mrz.document_code.startswith("P"):
        return out(PageKind.PASSPORT, "passport MRZ (P<)" + (" + PASSPORT" if has["passport"] else ""))
    if has["apostille"]:
        return out(PageKind.E_APOSTILLE, "Apostille")
    # An affidavit lists other documents by name ("Birth Certificate", "Mother's NID"), so it
    # is recognised before the documents it mentions.
    if has["affidavit"]:
        return out(PageKind.AFFIDAVIT, "Affidavit / same person")
    if mrz is not None and mrz.format == "TD1":
        return out(PageKind.NID, "ID-card MRZ (I<)")
    # A trade licence has the owner's birth-registration field; a birth certificate never
    # mentions a trade licence.
    if has["trade"] and not _only_translators_licence(text):
        return out(PageKind.TRADE_LICENSE, "Trade License")
    if has["death"]:
        return out(PageKind.DEATH_CERTIFICATE, "Death registration number / certificate")
    if has["birth"]:
        return out(PageKind.BIRTH_CERTIFICATE, "Birth Registration Number / BDRIS")
    if has["frc"] and has["frc_issuer"]:
        return out(PageKind.FRC, "Family certificate + local-government issuer")
    # After the FRC (a family certificate may list members' BRNs and dates of birth). The
    # registrar office, a date of birth, and two fields of the birth register, at least one
    # of them a register entry (Register No, Date of Registration, Order of Child); the
    # certificate's own BR number counts as the other. Citizenship certificates, cover
    # letters and checklists carry none of the register entries.
    if has["birth_registrar"] and has["date_of_birth"] and not _NOT_A_BIRTH_CERTIFICATE.search(text):
        fields = [name for name, rx in _REGISTER_FIELDS.items() if rx.search(text)]
        if fields and _has_own_brn(text):
            fields.append("BR Number")
        if len(fields) >= 2:
            return out(PageKind.BIRTH_CERTIFICATE, OLD_STYLE_BIRTH + ", ".join(fields))
    if has["challan"]:
        return out(PageKind.TAX_CHALLAN, "Challan form")
    if has["tax_ack"]:
        return out(PageKind.TAX_ACKNOWLEDGEMENT, "Acknowledgement receipt")
    if has["tax_cert"]:
        return out(PageKind.TAX_CERTIFICATE, "Income Tax Certificate")
    if has["tin"] or (has["nbr"] and re.search(r"\bTIN\b", text)):
        return out(PageKind.TIN_CERTIFICATE, "Taxpayer's Identification Number / NBR")
    if has["return_of_income"]:
        return out(PageKind.TAX_ACKNOWLEDGEMENT, "Return of income")
    # Generic identity words last: FRCs, trade licences and TINs all print NID numbers.
    if has["nid"]:
        return out(PageKind.NID, "National ID Card, no MRZ")
    if has["statement"] or _has_transaction_table(page):
        return out(PageKind.BANK_STATEMENT, "transaction table (Date/Debit/Credit/Balance)")
    if has["solvency"] or (has["to_whom"] and has["bank"] and has["account"]):
        return out(PageKind.BANK_SOLVENCY, "Solvency / account holder letter from a bank")
    if has["employment"] and not has["acad_cert"]:
        return out(PageKind.EMPLOYMENT_CERTIFICATE, "employment wording")
    if has["nid_number"]:
        return out(PageKind.NID, "NID number, no card title or MRZ")
    if has["transcript"] and has["acad_cert"]:
        return out(PageKind.ACADEMIC_TRANSCRIPT, "academic transcript / grade sheet")
    if has["acad_cert"] and has["acad_award"] and re.search(r"CERTIF(?:Y|IED|ICATE)", text, re.IGNORECASE):
        return out(PageKind.ACADEMIC_CERTIFICATE, "board/university certificate")
    # A personal statement also says "IELTS 6.5" or "TOPIK": the test's own form fields are needed too.
    if has["language_test"] and _LANGUAGE_FORM.search(text):
        return out(PageKind.LANGUAGE_TEST, "IELTS / TOPIK")
    return out(PageKind.IGNORED, "no signature matched (IGNORE-01)")


ACADEMIC = {PageKind.ACADEMIC_CERTIFICATE, PageKind.ACADEMIC_TRANSCRIPT}


def classify_pages(pages: Sequence[PageReading], today: date) -> list[PageClass]:
    """Classify every page, then apply the rules that need neighbouring pages.

    Academic certificates and transcripts count only inside an apostille block (section 1.1:
    "Apostille triggers the academic block"); elsewhere, e.g. a university's recommendation
    letter, they are ignored.
    """
    classes = [classify_page(p, today) for p in pages]
    in_block = False
    for i, c in enumerate(classes):
        if c.kind == PageKind.E_APOSTILLE:
            in_block = True
        elif c.kind in ACADEMIC:
            if not in_block:
                classes[i] = c.model_copy(
                    update={"kind": PageKind.IGNORED, "reason": c.reason + ", but outside an apostille block (IGNORE-01)"}
                )
        else:
            in_block = False
    return classes

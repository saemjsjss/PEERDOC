"""Field extractors: one page group in, one typed rules-engine document out.

Every value carries a confidence from `confidence.py`. Nothing is filled in by guesswork:
a field that can't be found stays empty, which the rules engine treats as FLAG.
"""

from __future__ import annotations

import html
import re
from itertools import permutations
from collections.abc import Callable, Sequence
from datetime import date

from hklv_ocr.reading import PageReading
from hklv_rules.models import documents as m
from hklv_rules.models.common import Extracted, NotaryInfo, Person

from .classify import PageKind
from .common_fields import NOTARY_RE, TRANSLATION_RE, document_language, has_translation, notary_info, page_language
from .confidence import AGREE_CAP, DISAGREE, MRZ_INVALID, MRZ_VALID, SINGLE_READER_FACTOR, VL_ONLY, date_field, derived, score_text, text_field
from .dates import parse_date, parse_words_date
from .group import PageGroup
from .mrz import MrzResult
from .text import Found, as_lines_page, clean_value, find_labeled, reading_order, squash

NAME = r"[A-Za-z][A-Za-z .\-']{1,60}"
# Labels that often follow a name on the same printed line.
NAME_STOPS = (
    r"Father", r"Mother", r"Husband", r"Spouse", r"Date", r"Sex", r"Gender", r"Nationality", r"Place",
    r"Address", r"NID", r"ID\s*No", r"A/C", r"Birth", r"Blood", r"Relation", r"S/O", r"D/O", r"W/O", r"Son\s+of",
)


# --- helpers ---------------------------------------------------------------------------


def _first(group: PageGroup, finder: Callable[[PageReading], Found | None], pages: Sequence[PageReading] | None = None):
    """First page where PP-OCRv6's lines give the value; else PaddleOCR-VL's text alone.

    A value only the second reader saw scores VL_ONLY (below threshold: FLAG). It is
    still better evidence than nothing, e.g. for one-digit-per-box numbers that PP-OCRv6
    partly misses.
    """
    pages = list(pages if pages is not None else group.pages)
    for page in pages:
        found = finder(page)
        if found is not None:
            return found, page
    for page in pages:
        found = finder(as_lines_page(page, VL_ONLY))
        if found is not None:
            return found, page
    return None, None


def _name(group: PageGroup, labels: Sequence[str], pages: Sequence[PageReading] | None = None) -> Extracted[str]:
    found, page = _first(
        group, lambda p: find_labeled(p, labels, value_pattern=NAME, stop_words=NAME_STOPS), pages
    )
    return text_field(found, page)


def _text(group: PageGroup, labels: Sequence[str], pattern: str, pages: Sequence[PageReading] | None = None) -> Extracted[str]:
    found, page = _first(group, lambda p: find_labeled(p, labels, value_pattern=pattern), pages)
    if found is not None:
        found = Found(re.sub(r"\s+", "", found.value) if re.fullmatch(r"[\d\s\-/]+", found.value) else found.value, found.score, found.page_no)
    return text_field(found, page)


def _date(group: PageGroup, labels: Sequence[str], pages: Sequence[PageReading] | None = None) -> Extracted[date]:
    found, page = _first(group, lambda p: find_labeled(p, labels, value_pattern=r".{6,40}"), pages)
    if found is None:
        return Extracted[date]()
    d = parse_date(found.value)
    if d is None:
        return Extracted[date]()
    return date_field(d, score_text(found, page), found.page_no)


def _mrz(group: PageGroup) -> MrzResult | None:
    zones = [c.mrz for c in group.classes if c.mrz is not None]
    zones.sort(key=lambda z: (z.valid, sum(z.checks.values())), reverse=True)
    return zones[0] if zones else None


def _mrz_conf(mrz: MrzResult, check: str) -> float:
    return MRZ_VALID if mrz.checks.get(check) and mrz.checks.get("composite", True) else MRZ_INVALID


def _mrz_page(group: PageGroup, mrz: MrzResult) -> int:
    for c in group.classes:
        if c.mrz is mrz:
            return c.page_no
    return group.pages[0].page_no


def _agree_with_mrz(printed: Extracted[str], mrz_name: str) -> Extracted[str]:
    """Printed name confirmed by the MRZ (word order ignored) is as good as two readers."""
    if printed.value is None or not mrz_name:
        return printed
    words = [w for w in mrz_name.split() if w]
    if sorted(squash(w) for w in printed.value.split()) == sorted(squash(w) for w in words):
        return Extracted[str](value=printed.value, confidence=max(printed.confidence, AGREE_CAP), source_page=printed.source_page)
    # Same letters, spacing lost on the card ("KARIMUDDIN"): take the MRZ's word breaks, in
    # the printed order. No letter is changed.
    for order in permutations(words):
        if squash("".join(order)) == squash(printed.value):
            return Extracted[str](value=" ".join(order), confidence=max(printed.confidence, AGREE_CAP), source_page=printed.source_page)
    return printed


def _translation_pages(group: PageGroup) -> list[PageReading]:
    return [p for p in group.pages if NOTARY_RE.search(p.line_text) or TRANSLATION_RE.search(p.line_text)]


def _notary(group: PageGroup) -> NotaryInfo:
    return notary_info(group.pages)


def _tables(page: PageReading) -> list[list[list[str]]]:
    """PaddleOCR-VL table blocks as rows of cell texts."""
    out = []
    for b in page.blocks:
        if b.label != "table" or "<tr" not in b.text.lower():
            continue
        rows = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", b.text, re.IGNORECASE | re.DOTALL):
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.IGNORECASE | re.DOTALL)
            rows.append([clean_value(html.unescape(re.sub(r"<[^>]+>", " ", c))) for c in cells])
        out.append(rows)
    return out


def _line_found(page: PageReading, value: str) -> Found | None:
    """Score a value taken from a VL table by finding it among PP-OCRv6's lines."""
    target = squash(value)
    if not target:
        return None
    for ln in page.lines:
        if target in squash(ln.text):
            return Found(value, ln.score, page.page_no)
    return None


def _table_field(page: PageReading, value: str) -> Extracted[str]:
    """A value read from a VL table, confirmed word by word by PP-OCRv6's lines.

    Table cells wrap over several PP-OCRv6 lines ("KAMAL UDDIN" / "S/O: ABDUL" / "KARIM&"), so
    each word is looked up on its own; every word found -> the weakest line's score.
    """
    value = clean_value(re.sub(r"(?<=[A-Za-z])(?=[SDW]/O\b)", " ", value))  # "UDDINS/O" -> "UDDIN S/O"
    if not value:
        return Extracted[str]()
    found = _line_found(page, value)
    if found is not None:
        return Extracted[str](value=value, confidence=round(min(found.score, AGREE_CAP), 4), source_page=page.page_no)
    scores = []
    for word in re.findall(r"[A-Za-z0-9]{2,}", value):
        hit = [ln.score for ln in page.lines if squash(word) in squash(ln.text)]
        if not hit:
            return Extracted[str](value=value, confidence=VL_ONLY, source_page=page.page_no)
        scores.append(max(hit))
    conf = min(min(scores), AGREE_CAP) if scores else VL_ONLY
    return Extracted[str](value=value, confidence=round(conf, 4), source_page=page.page_no)


# --- identity ----------------------------------------------------------------------------


def passport(group: PageGroup, doc_id: str) -> m.Passport:
    mrz = _mrz(group)
    # Labels are bilingual ("<Bangla>/Surname"); OCR often garbles them ("/Suame").
    surname = _name(group, [r"Surname", r"/\s*Su\w{0,3}me\b"])
    given = _name(group, [r"Given\s*Names?"])
    fields: dict = {}
    if mrz is not None:
        page_no = _mrz_page(group, mrz)
        ok_name = derived(mrz.surname or None, MRZ_VALID if mrz.valid else MRZ_INVALID, page_no)
        fields = {
            "passport_number": derived(mrz.document_number or None, _mrz_conf(mrz, "document_number"), page_no),
            "mrz_surname": ok_name,
            "mrz_given_names": derived(mrz.given_names or None, MRZ_VALID if mrz.valid else MRZ_INVALID, page_no),
            "date_of_birth": date_field(mrz.birth_date, _mrz_conf(mrz, "birth_date"), page_no),
            "date_of_expiry": date_field(mrz.expiry_date, _mrz_conf(mrz, "expiry_date"), page_no),
        }
        surname = _agree_with_mrz(surname, mrz.surname)
        given = _agree_with_mrz(given, mrz.given_names)
    else:
        fields = {
            "passport_number": _text(group, [r"Passport\s*No\.?", r"Passport\s*Number"], r"[A-Z]{1,2}\d{7,8}"),
            "date_of_birth": _date(group, [r"Date\s*of\s*Birth"]),
            "date_of_expiry": _date(group, [r"Date\s*of\s*Expiry"]),
        }
    return m.Passport(
        doc_id=doc_id,
        pages=group.page_nos,
        surname=surname,
        given_names=given,
        father_name=_name(group, [r"Father'?s?\s*Name"]),
        mother_name=_name(group, [r"Mother'?s?\s*Name"]),
        **fields,
    )


NID_NUMBER = r"\d[\d ]{8,20}\d"
NID_LABELS = [r"NID\s*(?:No|Number)\.?", r"ID\s*NO\.?", r"National\s*ID\s*(?:No|Number)\.?", r"Smart\s*Card\s*No\.?"]


def nid(group: PageGroup, doc_id: str) -> m.NationalId:
    mrz = _mrz(group)
    translation = _translation_pages(group)
    card_pages = [p for p in group.pages if p not in translation] or group.pages
    name = _name(group, [r"Name"], pages=card_pages)
    if name.value is None:
        name = _name(group, [r"Name"])
    if mrz is not None:
        page_no = _mrz_page(group, mrz)
        name = _agree_with_mrz(name, mrz.full_name)
        number_on_card = derived(mrz.document_number or None, _mrz_conf(mrz, "document_number"), page_no)
        dob = date_field(mrz.birth_date, _mrz_conf(mrz, "birth_date"), page_no)
    else:
        number_on_card = _text(group, NID_LABELS, NID_NUMBER, pages=card_pages)
        dob = _date(group, [r"Date\s*of\s*Birth"], pages=card_pages)
    number_on_translation = _text(group, NID_LABELS, NID_NUMBER, pages=translation) if translation else Extracted[str]()
    return m.NationalId(
        doc_id=doc_id,
        pages=group.page_nos,
        variant=m.NidVariant.DIGITAL if mrz is not None and mrz.format == "TD1" else m.NidVariant.OLD,
        cardholder_name=name,
        date_of_birth=dob,
        number_on_card=number_on_card,
        number_on_translation=number_on_translation,
        has_english_translation=(
            Extracted[bool](value=True, confidence=0.95, source_page=translation[0].page_no)
            if translation
            else has_translation(group.pages)
        ),
        notary=_notary(group),
    )


def birth_certificate(group: PageGroup, doc_id: str) -> m.BirthCertificate:
    english = [p for p in group.pages if page_language(p).value == "ENGLISH"] or group.pages
    return m.BirthCertificate(
        doc_id=doc_id,
        pages=group.page_nos,
        registration_number=_text(group, [r"Birth\s*Registration\s*(?:Number|No)\.?", r"Registration\s*No\.?"], r"\d[\d ]{15,20}\d", pages=english),
        name=_name(group, [r"(?<!Father's )(?<!Mother's )Name(?:\s*of\s*(?:the\s*)?Child)?"], pages=english),
        date_of_birth=_date(group, [r"Date\s*of\s*Birth"], pages=english),
        father_name=_name(group, [r"Father'?s?\s*Name"], pages=english),
        mother_name=_name(group, [r"Mother'?s?\s*Name"], pages=english),
        language=document_language(group.pages),
        has_english_translation=has_translation(group.pages),
        notary=_notary(group),
    )


def death_certificate(group: PageGroup, doc_id: str) -> m.DeathCertificate:
    return m.DeathCertificate(
        doc_id=doc_id,
        pages=group.page_nos,
        registration_number=_text(group, [r"Death\s*Registration\s*(?:Number|No)\.?", r"Registration\s*No\.?"], r"\d[\d ]{8,20}\d"),
        deceased_name=_name(group, [r"Name\s*of\s*(?:the\s*)?Deceased", r"Deceased'?s?\s*Name", r"Name"]),
        date_of_death=_date(group, [r"Date\s*of\s*Death"]),
        language=document_language(group.pages),
        has_english_translation=has_translation(group.pages),
        notary=_notary(group),
    )


_RELATION_WORDS = ("SELF", "HIMSELF", "HERSELF", "APPLICANT", "FATHER", "MOTHER", "BROTHER", "SISTER", "SON", "DAUGHTER", "WIFE", "HUSBAND", "SPOUSE")


def frc(group: PageGroup, doc_id: str) -> m.FamilyRelationshipCertificate:
    from .classify import SIG

    issuer_found = None
    for page in group.pages:
        for ln in reading_order(page.lines):
            if SIG["frc_issuer"].search(ln.text):
                issuer_found = (Found(clean_value(ln.text), ln.score, page.page_no), page)
                break
        if issuer_found:
            break
    members: list[m.FrcMember] = []
    for page in group.pages:
        for table in _tables(page):
            header = [c.upper() for c in table[0]] if table else []
            name_col = next((i for i, c in enumerate(header) if "NAME" in c), None)
            rel_col = next((i for i, c in enumerate(header) if "RELATION" in c), None)
            dob_col = next((i for i, c in enumerate(header) if "BIRTH" in c or "DOB" in c), None)
            if name_col is None or rel_col is None:
                continue
            for row in table[1:]:
                if len(row) <= max(name_col, rel_col):
                    continue
                dob = parse_date(row[dob_col]) if dob_col is not None and dob_col < len(row) else None
                members.append(
                    m.FrcMember(
                        name=_table_field(page, row[name_col]),
                        relation=_table_field(page, row[rel_col]),
                        date_of_birth=date_field(dob, _table_field(page, row[dob_col]).confidence, page.page_no) if dob else Extracted[date](),
                    )
                )
    issue_date = _date(group, [r"Date\s*of\s*Issue", r"Issue\s*Date", r"Issued\s*on"])
    if issue_date.value is None:
        # Letter-style header: "Ref: ABC/1/2026  Date: 01-10-2026" (first "Date", top of page).
        issue_date = _date(group, [r"\bDate\b(?!\s*of)"])
    return m.FamilyRelationshipCertificate(
        doc_id=doc_id,
        pages=group.page_nos,
        issuer_text=text_field(*issuer_found) if issuer_found else Extracted[str](),
        members=tuple(members),
        issue_date=issue_date,
        registration_date=_date(group, [r"Date\s*of\s*Registration", r"Registration\s*Date"]),
        notary=_notary(group),
    )


_PERSON_OF = (
    (re.compile(r"\bMOTHER", re.IGNORECASE), Person.MOTHER),
    (re.compile(r"\bFATHER", re.IGNORECASE), Person.FATHER),
    (re.compile(r"\bMY\s+NAME\b|\bOWN\s+NAME\b|\bSELF\b", re.IGNORECASE), Person.STUDENT),
)


def _person(text: str) -> Person | None:
    for rx, person in _PERSON_OF:
        if rx.search(text):
            return person
    return None


def affidavit(group: PageGroup, doc_id: str) -> m.Affidavit:
    deponent = None
    for page in group.pages:
        for ln in reading_order(page.lines):
            mt = re.search(r"\bI\s*,\s*([A-Za-z][A-Za-z .\-']{1,60}?)\s*,", ln.text)
            if mt:
                deponent = (Found(clean_value(mt.group(1)), ln.score, page.page_no), page)
                break
        if deponent:
            break
    same = [(p, ln) for p in group.pages for ln in p.lines if re.search(r"SAME\s+PERSON", ln.text, re.IGNORECASE)]
    states_same = (
        Extracted[bool](value=True, confidence=round(min(max(ln.score for _, ln in same), AGREE_CAP), 4), source_page=same[0][0].page_no)
        if same
        else Extracted[bool](value=False, confidence=0.8, source_page=group.pages[0].page_no)
    )
    # Two tables: names as written in some documents, then the different spelling elsewhere.
    tables = [(page, t) for page in group.pages for t in _tables(page)]
    by_person: dict[Person, dict[str, Extracted[str]]] = {}
    for idx, (page, table) in enumerate(tables[:2]):
        slot = "existing_name" if idx == 0 else "different_name"
        for row in table:
            if len(row) < 2:
                continue
            person = _person(row[-1]) or _person(" ".join(row))
            if person is None:
                continue
            name_cell = next((c for c in reversed(row[:-1]) if re.fullmatch(NAME, c or "") and _person(c) is None and "DOCUMENT" not in c.upper()), None)
            if name_cell:
                by_person.setdefault(person, {})[slot] = _table_field(page, name_cell)
    entries = tuple(
        m.AffidavitEntry(person=p, existing_name=v.get("existing_name", Extracted[str]()), different_name=v.get("different_name", Extracted[str]()))
        for p, v in by_person.items()
    )
    return m.Affidavit(
        doc_id=doc_id,
        pages=group.page_nos,
        deponent_name=text_field(*deponent) if deponent else Extracted[str](),
        states_same_person=states_same,
        entries=entries,
        notary=_notary(group),
    )


# --- financial ---------------------------------------------------------------------------

ACCOUNT_NO = r"[0-9][0-9 \-]{5,24}[0-9]"
ACCOUNT_LABELS = [r"A/?C\.?\s*(?:No|Number)\.?", r"Account\s*(?:No|Number)\.?"]


def _holder_from_sentence(group: PageGroup) -> Extracted[str]:
    """'This is to certify that ABDUL KARIM, Son of ...' -> ABDUL KARIM."""
    rx = re.compile(r"certify\s+that\s+(?:Mr\.?|Mrs\.?|Ms\.?|Md\.?\s)?\s*([A-Za-z][A-Za-z .\-']{1,60}?)\s*(?:,|\bS/O\b|\bD/O\b|\bW/O\b|\bson\b|\bdaughter\b|\bwife\b|\bmaintain|\bhas\b|\bis\b)", re.IGNORECASE)
    for page in group.pages:
        lines = reading_order(page.lines)
        for i, ln in enumerate(lines):
            joined = ln.text + (" " + lines[i + 1].text if i + 1 < len(lines) else "")
            mt = rx.search(joined)
            if mt:
                return text_field(Found(clean_value(mt.group(1)), ln.score, page.page_no), page)
    return Extracted[str]()


def bank_solvency(group: PageGroup, doc_id: str) -> m.BankSolvency:
    # The letter's own sentence first; its details table has column headers ("Name of
    # Account | Account Number | Balance") that a label search would read as the value.
    holder = _holder_from_sentence(group)
    if holder.value is None:
        holder = _name(group, [r"Account\s*Holder(?:'s)?\s*(?:Name)?", r"A/?C\s*Name"])
    return m.BankSolvency(
        doc_id=doc_id,
        pages=group.page_nos,
        account_holder=holder,
        account_number=_text(group, ACCOUNT_LABELS, ACCOUNT_NO),
        letter_date=_date(group, [r"Date", r"Dated"]),
    )


def bank_statement(group: PageGroup, doc_id: str) -> m.BankStatement:
    return m.BankStatement(
        doc_id=doc_id,
        pages=group.page_nos,
        account_holder=_name(group, [r"Account\s*Name", r"A/?C\s*Name", r"Customer\s*Name", r"Account\s*Holder", r"Name"]),
        account_number=_text(group, ACCOUNT_LABELS, ACCOUNT_NO),
        statement_date=_date(group, [r"Generation\s*Date", r"Generated\s*(?:on|Date)", r"As\s*on", r"Print(?:ing)?\s*Date", r"Printed\s*on", r"Statement\s*Date"]),
    )


def trade_license(group: PageGroup, doc_id: str) -> m.TradeLicense:
    english = [p for p in group.pages if page_language(p).value == "ENGLISH"] or group.pages
    fy = None
    found, page = _first(
        group,
        lambda p: find_labeled(p, [r"Fiscal\s*Year", r"Financial\s*Year", r"Assessment\s*Year", r"F\.\s?Y\.?"], value_pattern=r"20\d{2}\s*[-–/]\s*(?:20)?\d{2}"),
        english,
    )
    if found is not None:
        mt = re.match(r"(20\d{2})\s*[-–/]\s*((?:20)?\d{2})", found.value)
        end = mt.group(2) if len(mt.group(2)) == 4 else mt.group(1)[:2] + mt.group(2)
        fy = (Found(f"{mt.group(1)}-{end}", found.score, found.page_no), page)
    return m.TradeLicense(
        doc_id=doc_id,
        pages=group.page_nos,
        license_number=_text(group, [r"Licen[cs]e\s*(?:No|Number)\.?", r"Trade\s*Licen[cs]e\s*(?:No|Number)\.?"], r"[A-Z0-9/\-]*\d{6,}[A-Z0-9/\-]*", pages=english),
        owner_name=_name(group, [r"Name\s*of\s*(?:the\s*)?(?:Proprietor|Owner)(?:\s*/\s*Assessee)?", r"Proprietor'?s?\s*Name", r"Owner'?s?\s*Name"], pages=english),
        fiscal_year=text_field(*fy) if fy else Extracted[str](),
        language=document_language(group.pages),
        has_english_translation=has_translation(group.pages),
        notary=_notary(group),
    )


def employment_certificate(group: PageGroup, doc_id: str) -> m.EmploymentCertificate:
    employed = [(p, ln) for p in group.pages for ln in p.lines if re.search(r"\bIS\s+(?:WORKING|EMPLOYED|SERVING)\b|\bCURRENTLY\b", ln.text, re.IGNORECASE)]
    return m.EmploymentCertificate(
        doc_id=doc_id,
        pages=group.page_nos,
        employee_name=_holder_from_sentence(group),
        issue_date=_date(group, [r"Date", r"Dated"]),
        currently_employed=(
            Extracted[bool](value=True, confidence=round(min(employed[0][1].score, AGREE_CAP), 4), source_page=employed[0][0].page_no)
            if employed
            else Extracted[bool]()
        ),
        language=document_language(group.pages),
        has_english_translation=has_translation(group.pages),
        notary=_notary(group),
    )


TIN_RE = re.compile(r"\b(\d{12})\b")


def tin_certificate(group: PageGroup, doc_id: str) -> m.TinCertificate:
    qr = next((b for p in group.pages for b in p.barcodes if b.format.upper().startswith("QR")), None)
    tin_from_qr = None
    if qr is not None:
        mt = re.search(r"TIN\s*(?:No\.?)?\s*[:\-]?\s*(\d{12})", qr.text, re.IGNORECASE) or TIN_RE.search(qr.text)
        tin_from_qr = mt.group(1) if mt else None
    return m.TinCertificate(
        doc_id=doc_id,
        pages=group.page_nos,
        taxpayer_name=_name(group, [r"(?<!Father's )(?<!Mother's )Name(?!\s*of)",r"Taxpayer'?s?\s*Name"]),
        tin_printed=_text(group, [r"\bTIN\b(?:\s*No\.?)?"], r"\d{12}"),
        qr_decoded=qr is not None,
        tin_from_qr=tin_from_qr,
    )


def _amount(group: PageGroup, labels: Sequence[str]):
    from decimal import Decimal, InvalidOperation

    found, page = _first(group, lambda p: find_labeled(p, labels, value_pattern=r"[\d,]+(?:\.\d{1,2})?"))
    if found is None:
        return Extracted()
    try:
        value = Decimal(found.value.replace(",", ""))
    except InvalidOperation:
        return Extracted()
    return Extracted(value=value, confidence=round(score_text(found, page), 4), source_page=found.page_no)


def tax_challan(group: PageGroup, doc_id: str) -> m.IncomeTaxChallan:
    return m.IncomeTaxChallan(
        doc_id=doc_id,
        pages=group.page_nos,
        challan_number=_text(group, [r"Challan\s*(?:No|Number)\.?", r"Transaction\s*ID"], r"[A-Z0-9][A-Z0-9\-]{5,30}"),
        printed_amount=_amount(group, [r"Amount", r"Total\s*Amount", r"Taka"]),
    )


def tax_acknowledgement(group: PageGroup, doc_id: str) -> m.IncomeTaxAcknowledgement:
    return m.IncomeTaxAcknowledgement(
        doc_id=doc_id,
        pages=group.page_nos,
        total_tax_paid=_amount(group, [r"Total\s*Tax\s*Paid", r"Tax\s*Paid"]),
        total_income=_amount(group, [r"Total\s*Income(?:\s*Shown)?"]),
    )


def tax_certificate(group: PageGroup, doc_id: str) -> m.IncomeTaxCertificate:
    return m.IncomeTaxCertificate(doc_id=doc_id, pages=group.page_nos, taxpayer_name=_holder_from_sentence(group))


# --- academic ----------------------------------------------------------------------------

_LEVELS = (
    (r"HIGHER\s*SECONDARY", m.AcademicLevel.HSC),
    (r"SECONDARY\s*SCHOOL\s*CERTIFICATE", m.AcademicLevel.SSC),
    (r"\bDAKHIL\b", m.AcademicLevel.DAKHIL),
    (r"\bALIM\b", m.AcademicLevel.ALIM),
    (r"\bDIPLOMA\b", m.AcademicLevel.DIPLOMA),
    (r"\bMASTER", m.AcademicLevel.MASTERS),
    (r"\bBACHELOR\b|\bB\.?\s?B\.?\s?A\b|\bB\.?\s?SC\b|\bB\.?\s?A\b(?=.*HONOU?RS)", m.AcademicLevel.BACHELOR),
    (r"\bH\.?\s?S\.?\s?C\b", m.AcademicLevel.HSC),
    (r"\bS\.?\s?S\.?\s?C\b", m.AcademicLevel.SSC),
)


_RANK = {
    m.AcademicLevel.SSC: 1, m.AcademicLevel.DAKHIL: 1,
    m.AcademicLevel.HSC: 2, m.AcademicLevel.ALIM: 2, m.AcademicLevel.DIPLOMA: 2,
    m.AcademicLevel.BACHELOR: 3, m.AcademicLevel.MASTERS: 4,
}


def _level(group: PageGroup) -> Extracted:
    """The highest level the page names: a bachelor transcript also says "HSC or equivalent"
    (its entry requirement), an HSC certificate never names a degree."""
    page = group.pages[0]
    hits = []
    for pattern, level in _LEVELS:
        line = next((ln for ln in page.lines if re.search(pattern, ln.text, re.IGNORECASE)), None)
        if line is not None:
            hits.append((level, line))
    if not hits:
        return Extracted[m.AcademicLevel](value=m.AcademicLevel.OTHER, confidence=0.5, source_page=page.page_no)
    level, line = max(hits, key=lambda h: _RANK[h[0]])
    return Extracted[m.AcademicLevel](value=level, confidence=round(min(line.score, AGREE_CAP), 4), source_page=page.page_no)


def _student_name(group: PageGroup) -> Extracted[str]:
    labelled = _name(group, [r"Name\s*of\s*(?:the\s*)?(?:Student|Candidate)", r"Student'?s?\s*Name", r"Candidate'?s?\s*Name"])
    if labelled.value is not None:
        return labelled
    # Certificates: "This is to Certify that <name>" with the name on the same or next line.
    for page in group.pages:
        lines = reading_order(page.lines)
        for i, ln in enumerate(lines):
            mt = re.search(r"certify\s+that\s*(.*)$", ln.text, re.IGNORECASE)
            if not mt:
                continue
            candidate = clean_value(mt.group(1))
            src = ln
            if not candidate and i + 1 < len(lines):
                candidate, src = clean_value(lines[i + 1].text), lines[i + 1]
            candidate = re.split(r"\s+(?:Son|Daughter|S/O|D/O)\b", candidate, flags=re.IGNORECASE)[0]
            if re.fullmatch(NAME, candidate or ""):
                return text_field(Found(candidate, src.score, page.page_no), page)
    return Extracted[str]()


def _certificate_dob(group: PageGroup) -> Extracted[date]:
    labelled = _date(group, [r"Date\s*of\s*Birth", r"Birth\s*Date"])
    if labelled.value is not None:
        return labelled
    # Board certificates write it out: "...date of birth as recorded in his/her registration
    # card is Fifth August Two Thousand." (often wrapped onto the next line).
    for page in group.pages:
        lines = reading_order(page.lines)
        for i, ln in enumerate(lines):
            if not re.search(r"date\s*of\s*birth", ln.text, re.IGNORECASE):
                continue
            used = lines[i : i + 3]
            d = parse_words_date(" ".join(x.text for x in used))
            if d is None:
                continue
            score = min(x.score for x in used)
            # The second reader must spell out the same date.
            vl = parse_words_date(page.block_text)
            if vl == d:
                conf = min(score, AGREE_CAP)
            elif vl is not None:
                conf = DISAGREE
            else:
                conf = score * SINGLE_READER_FACTOR
            return date_field(d, conf, page.page_no)
    return Extracted[date]()


def academic_certificate(group: PageGroup, doc_id: str) -> m.AcademicCertificate:
    return m.AcademicCertificate(
        doc_id=doc_id,
        pages=group.page_nos,
        level=_level(group),
        student_name=_student_name(group),
        date_of_birth=_certificate_dob(group),
    )


def academic_transcript(group: PageGroup, doc_id: str) -> m.AcademicTranscript:
    return m.AcademicTranscript(doc_id=doc_id, pages=group.page_nos, level=_level(group), student_name=_student_name(group))


def e_apostille(group: PageGroup, doc_id: str) -> m.EApostille:
    qr = next((b for p in group.pages for b in p.barcodes if b.format.upper().startswith("QR")), None)
    return m.EApostille(doc_id=doc_id, pages=group.page_nos, qr_decoded=qr is not None, qr_url=qr.text if qr is not None else None)


def photo(group: PageGroup, doc_id: str) -> m.Photo:
    return m.Photo(doc_id=doc_id, pages=group.page_nos)


EXTRACTORS: dict[PageKind, Callable[[PageGroup, str], object]] = {
    PageKind.PASSPORT: passport,
    PageKind.PHOTO: photo,
    PageKind.BIRTH_CERTIFICATE: birth_certificate,
    PageKind.NID: nid,
    PageKind.DEATH_CERTIFICATE: death_certificate,
    PageKind.FRC: frc,
    PageKind.AFFIDAVIT: affidavit,
    PageKind.BANK_SOLVENCY: bank_solvency,
    PageKind.BANK_STATEMENT: bank_statement,
    PageKind.TRADE_LICENSE: trade_license,
    PageKind.EMPLOYMENT_CERTIFICATE: employment_certificate,
    PageKind.TIN_CERTIFICATE: tin_certificate,
    PageKind.TAX_CHALLAN: tax_challan,
    PageKind.TAX_ACKNOWLEDGEMENT: tax_acknowledgement,
    PageKind.TAX_CERTIFICATE: tax_certificate,
    PageKind.E_APOSTILLE: e_apostille,
    PageKind.ACADEMIC_CERTIFICATE: academic_certificate,
    PageKind.ACADEMIC_TRANSCRIPT: academic_transcript,
}

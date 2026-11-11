"""Regression tests for the 2026-11-12 code review (docs/code-review-2026-11-12.md). Fictional data."""

from datetime import date
from decimal import Decimal

import pytest
from builders import MOTHER, STUDENT, by_rule, context, frc, member
from reading_builders import make_page, qr

from hklv_extract.classify import PageKind, classify_page
from hklv_extract.extractors import bank_solvency, birth_certificate, tax_challan, tin_certificate
from hklv_extract.group import PageGroup
from hklv_rules.models import Outcome
from hklv_rules.rules import check_frc

TODAY = date(2026, 11, 11)


def _group(kind, *pages):
    return PageGroup(kind=kind, pages=list(pages))


# --- B2: letters quoting an NID number are not NID cards ---------------------------------


def test_solvency_letter_quoting_nid_number_is_a_solvency():
    page = make_page([
        "SOLVENCY CERTIFICATE",
        "This is to certify that Md Abdul Karim, NID No: 1234567890,",
        "maintains A/C No 0123456789 with our bank.",
    ])
    assert classify_page(page, TODAY).kind == PageKind.BANK_SOLVENCY


def test_employment_letter_quoting_nid_number_is_an_employment_certificate():
    page = make_page([
        "TO WHOM IT MAY CONCERN",
        "Md Abdul Karim (NID No. 1234567890) is working as Manager",
        "in our company since 2015.",
    ])
    assert classify_page(page, TODAY).kind == PageKind.EMPLOYMENT_CERTIFICATE


def test_bare_nid_number_page_is_still_an_nid():
    assert classify_page(make_page(["Name: KAMAL UDDIN", "NID No: 1234567890"]), TODAY).kind == PageKind.NID


# --- M1: solvency letter date is not the account opening date ----------------------------


def test_solvency_date_skips_account_opening_date():
    page = make_page([
        "SOLVENCY CERTIFICATE",
        "Account Opening Date: 01/02/2015",
        "Date: 10/11/2026",
        "This is to certify that Md Abdul Karim maintains A/C No 0123456789 with our bank.",
    ])
    assert bank_solvency(_group(PageKind.BANK_SOLVENCY, page), "s").letter_date.value == date(2026, 11, 10)


# --- M2: "Fathers Name" without the apostrophe is not the person's own name ---------------


def test_tin_name_ignores_fathers_name_without_apostrophe():
    page = make_page([
        "Taxpayer's Identification Number (TIN) Certificate",
        "TIN: 123456789012",
        "Fathers Name: ABDUL RAHIM",
        "Name: ABDUL KARIM",
    ])
    assert tin_certificate(_group(PageKind.TIN_CERTIFICATE, page), "t").taxpayer_name.value == "ABDUL KARIM"


def test_birth_certificate_name_ignores_fathers_name_without_apostrophe():
    page = make_page([
        "Birth Registration Certificate",
        "Fathers Name: ABDUL RAHIM",
        "Name: MD TANVIR AHMED RONY",
        "Date of Birth: 03-12-2000",
    ])
    assert birth_certificate(_group(PageKind.BIRTH_CERTIFICATE, page), "b").name.value == "MD TANVIR AHMED RONY"


# --- M4 and currency: challan amount and number -------------------------------------------


def test_challan_amount_skips_amount_in_words():
    page = make_page(["Challan No: 2526-0012345678", "Amount in words: Ten thousand", "5,000", "Total Amount: 10,000"])
    assert tax_challan(_group(PageKind.TAX_CHALLAN, page), "c").printed_amount.value == Decimal("10000")


def test_amount_with_currency_prefix_is_read():
    page = make_page(["Challan No: 2526-0012345678", "Total Amount: Tk. 12,000/-"])
    assert tax_challan(_group(PageKind.TAX_CHALLAN, page), "c").printed_amount.value == Decimal("12000")


def test_challan_number_comes_from_the_qr_first():
    page = make_page(["Challan No: 2526-0012345O78", "Total Amount: 10,000"], barcodes=[qr("ChallanNo=2526-0012345678")])
    number = tax_challan(_group(PageKind.TAX_CHALLAN, page), "c").challan_number
    assert number.value == "2526-0012345678"
    assert number.confidence > 0.9


# --- M3: FRC relation variants ---------------------------------------------------------------

def _frc_rules(*members):
    return by_rule(check_frc(context(frc(members=members))))


@pytest.mark.parametrize("father", ["Father (Late)", "Father's", "FATHER-LATE", "পিতা"])
def test_father_relation_variants_count_as_father(father):
    r = _frc_rules(member(STUDENT, "SELF"), member("MOHAMMAD KAMAL UDDIN", father), member(MOTHER, "MOTHER"))
    assert r["FRC-03"].outcome is Outcome.PASS


@pytest.mark.parametrize("me", ["Self (Applicant)", "নিজ"])
def test_self_relation_variants_count_as_self(me):
    r = _frc_rules(member(STUDENT, me), member("MOHAMMAD KAMAL UDDIN", "FATHER"), member(MOTHER, "MOTHER"))
    assert r["FRC-02"].outcome is Outcome.PASS


def test_father_in_law_is_not_the_father():
    r = _frc_rules(member(STUDENT, "SELF"), member("MOHAMMAD KAMAL UDDIN", "Father-in-law"), member(MOTHER, "MOTHER"))
    assert r["FRC-03"].outcome is Outcome.FAIL


def test_unknown_bangla_relation_flags_instead_of_failing():
    r = _frc_rules(member(STUDENT, "SELF"), member("MOHAMMAD KAMAL UDDIN", "জনক"), member(MOTHER, "MOTHER"))
    assert r["FRC-03"].outcome is Outcome.FLAG


# --- MRZ birth-date century pivot -------------------------------------------------------------


def test_mrz_birth_date_later_this_year_is_last_century():
    from hklv_extract.mrz import _date

    assert _date("261201", birth=True, today=date(2026, 11, 12)) == date(1926, 12, 1)
    assert _date("261101", birth=True, today=date(2026, 11, 12)) == date(2026, 11, 1)
    assert _date("261201", birth=False, today=date(2026, 11, 12)) == date(2026, 12, 1)


# --- an extractor crash FLAGs that document instead of failing the case ------------------------


def test_extractor_exception_leaves_an_empty_document(monkeypatch):
    from hklv_extract import build
    from hklv_ocr.reading import CaseReading

    def boom(group, doc_id):
        raise ValueError("unexpected layout")

    from hklv_rules.models import TinCertificate

    boom.__annotations__ = {"return": TinCertificate}
    monkeypatch.setitem(build.EXTRACTORS, PageKind.TIN_CERTIFICATE, boom)
    page = make_page(["Taxpayer's Identification Number (TIN) Certificate", "TIN: 123456789012"])
    case, _ = build.build_case(CaseReading(pages=(page,)), "c", TODAY)
    (doc,) = case.documents
    assert doc.doc_id == "tin_certificate-1" and not doc.taxpayer_name.found


# --- old BDR Form-3 small print: OCR slips in the labels --------------------------------------


def test_old_form_labels_with_ocr_slips_are_still_found():
    page = make_page([
        "Birth Registration Certificate",
        "BRNMiumber: 2 0 0 2 1 2 3 4 5 6 7 8 9 0 1 2 3",
        "Name: MD KAMAL UDDIN RANA",
        "Fathar's Name: MD ABDUL KARIM",
        "Motfiar's Name: MST RINA BEGUM",
    ])
    cert = birth_certificate(_group(PageKind.BIRTH_CERTIFICATE, page), "b")
    assert cert.registration_number.value == "20021234567890123"
    assert cert.father_name.value == "MD ABDUL KARIM"
    assert cert.mother_name.value == "MST RINA BEGUM"
    assert cert.name.value == "MD KAMAL UDDIN RANA"


def test_solvency_print_date_counts_as_the_letter_date():
    page = make_page([
        "SOLVENCY CERTIFICATE",
        "Print Date15-Jun-2025",
        "Opening Date : 11-Feb-1998",
        "This is to certify that Md Abdul Karim maintains A/C No 0123456789 with our bank.",
    ])
    assert bank_solvency(_group(PageKind.BANK_SOLVENCY, page), "s").letter_date.value == date(2025, 6, 15)


def test_translated_nid_on_agency_letterhead_is_an_nid_not_a_trade_licence():
    page = make_page([
        "GLOBAL TRANSLATION CENTRE",
        "Trade Licence No. 136130",
        "(Translated Copy)",
        "GOVERNMENT OF THE PEOPLE'S REPUBLIC OF BANGLADESH",
        "NATIONAL ID CARD",
        "Name: MD TANVIR AHMED",
        "NID No.: 1234509876",
    ])
    assert classify_page(page, TODAY).kind == PageKind.NID


def test_translated_trade_licence_is_still_a_trade_licence():
    page = make_page([
        "GLOBAL TRANSLATION CENTRE",
        "Trade Licence No. 136130",
        "(Translated Copy)",
        "TRADE LICENSE",
        "Name of the Proprietor: MD SHARIFUL ISLAM",
    ])
    assert classify_page(page, TODAY).kind == PageKind.TRADE_LICENSE


def test_photo_saved_as_a_pdf_is_a_photo():
    from hklv_ocr.reading import LayoutBlock

    picture = LayoutBlock(label="image", box=(100, 100, 900, 1100))
    photo = make_page([]).model_copy(update={"blocks": (picture,)})
    blank = make_page([]).model_copy(update={"blocks": ()})
    assert classify_page(photo, TODAY).kind == PageKind.PHOTO
    assert classify_page(blank, TODAY).kind != PageKind.PHOTO


def test_stamp_glyphs_beside_a_label_do_not_hide_the_value_below():
    from hklv_extract.text import find_labeled
    from hklv_ocr.reading import TextLine

    page = make_page([]).model_copy(update={"lines": (
        TextLine(text="Surname", score=0.99, box=(460, 976, 590, 994)),
        TextLine(text="6", score=0.43, box=(758, 976, 776, 993)),
        TextLine(text="合", score=0.46, box=(809, 970, 826, 990)),
        TextLine(text="AHMED", score=1.0, box=(477, 1000, 555, 1018)),
    )})
    assert find_labeled(page, ["Surname"], value_pattern=r"[A-Za-z][A-Za-z .\-']{1,60}").value == "AHMED"


def test_year_first_dates_with_slashes_or_dots_parse():
    from hklv_extract.dates import parse_date

    assert parse_date("2003/04/05") == date(2003, 4, 5)
    assert parse_date("2003.04.05") == date(2003, 4, 5)
    assert parse_date("99/2025/04/12") == date(2025, 4, 12)  # TOPIK: round number before the date
    assert parse_date("2003/04-05") is None  # mixed separators: not a date


def test_topik_score_report_table_is_read_by_column():
    from hklv_extract.extractors import language_test
    from hklv_ocr.reading import TextLine

    def line(text, x0, y0, x1, y1):
        return TextLine(text=text, score=0.99, box=(x0, y0, x1, y1))

    page = make_page([]).model_copy(update={"lines": (
        line("OFFICIAL TOPIK SCORE REPORT", 741, 333, 1738, 390),
        line("Name", 835, 657, 963, 699), line("Gender", 1355, 658, 1513, 697),
        line("Country", 1686, 657, 1861, 706), line("Date of Birth", 2042, 656, 2311, 697),
        line("2004/03/06", 2056, 736, 2297, 777), line("AHMED MD TANVIR", 682, 766, 1120, 802),
        line("M", 1409, 790, 1460, 833), line("BANGLADESH", 1627, 789, 1922, 829),
        line("Test Held/Test Date", 1449, 926, 1860, 963), line("99/2025/04/12", 1501, 1000, 1808, 1038),
    )})
    t = language_test(_group(PageKind.LANGUAGE_TEST, page), "l")
    assert t.candidate_name.value == "AHMED MD TANVIR"
    assert t.date_of_birth.value == date(2004, 3, 6)
    assert t.test_date.value == date(2025, 4, 12)


def test_frc_misspelt_title_is_still_an_frc():
    page = make_page(["03 NO. CHANDLA UNION PARISHAD", "FAMILY RELATIONSHIP CERTIFICTE", "NID NO-1234567890"])
    assert classify_page(page, TODAY).kind == PageKind.FRC


def test_frc_applicant_named_under_the_table_counts_as_the_applicant_row():
    from hklv_extract.extractors import frc as frc_extract

    page = make_page(["UNION PARISHAD", "Family Relationship Certificate", "Applicant Name: TANVIR AHMED"])
    members = frc_extract(_group(PageKind.FRC, page), "f").members
    assert [(mb.relation.value, mb.name.value) for mb in members] == [("APPLICANT", "TANVIR AHMED")]
    assert members[0].relation.confidence >= 0.9


def test_frc_rows_the_table_reader_dropped_flag_instead_of_fail():
    from hklv_extract.extractors import frc as frc_extract

    page = make_page(["UNION PARISHAD", "Family Relationship Certificate", "SELF", "FATHER", "MOTHER"])
    members = frc_extract(_group(PageKind.FRC, page), "f").members
    assert {mb.relation.value for mb in members} == {"SELF", "FATHER", "MOTHER"}
    assert all(not mb.relation.is_reliable(0.9) for mb in members)

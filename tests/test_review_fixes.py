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



# --- a digit in the MRZ name is an OCR slip; an agreeing MRZ confirms a shaky print --------


def _passport_ctx(mrz_surname, printed_confidence):
    from builders import birth_certificate, ex, passport

    p = passport(surname="AFROZ", mrz_surname=mrz_surname)
    p = p.model_copy(update={"surname": ex("AFROZ", printed_confidence)})
    return context(p, birth_certificate(name="TANVIR AFROZ"), with_identity_docs=False)


def test_mrz_zero_for_o_confirms_a_low_confidence_printed_name():
    from builders import LOW

    from hklv_rules.rules import check_passport

    ctx = _passport_ctx("AFR0Z", LOW)
    assert ctx.anchors.student.certain
    assert by_rule(check_passport(ctx))["PASSPORT-01"].outcome is Outcome.PASS


def test_mrz_that_disagrees_still_leaves_a_low_confidence_print_uncertain():
    from builders import LOW

    from hklv_rules.rules import check_passport

    ctx = _passport_ctx("AFROSE", LOW)
    assert not ctx.anchors.student.certain
    assert by_rule(check_passport(ctx))["PASSPORT-01"].outcome is Outcome.FLAG


# --- pages that only mention a trade licence or a language test ----------------------------


def test_agency_letterhead_with_misread_licence_number_is_not_a_trade_licence():
    page = make_page([
        "Govt. Approved Translation Reg. No.: 27",
        "Trade License No.: D60631",  # OCR read the 0 as D
        "TRANSLATED TRUE COPY",
        "Office Order",
        "The following students are directed to undergo training.",
    ])
    assert classify_page(page, TODAY).kind is not PageKind.TRADE_LICENSE


def test_personal_statement_mentioning_ielts_is_not_a_language_test():
    page = make_page([
        "I achieved Level 1 in the 102nd TOPIK I examination in October 2025.",
        "I also obtained an overall IELTS score of 6.5 in January 2026.",
    ])
    assert classify_page(page, TODAY).kind is PageKind.IGNORED


def test_ielts_test_report_form_is_a_language_test():
    page = make_page(["IELTS", "Test Report Form", "Candidate Number 123456", "Overall Band Score 6.5"])
    assert classify_page(page, TODAY).kind is PageKind.LANGUAGE_TEST


@pytest.mark.parametrize(
    "line_text,reliable",
    [("HAS CONFERRED THE DEGREE OF", True), ("Result Published on 08 January 2025", False)],
)
def test_degree_under_the_notary_stamp_read_from_the_layout_text(line_text, reliable):
    # The stamp hides "Bachelor of Science" from the line reader; the layout reader has it
    # inside the stamp's block. Trusted only when the page confers a degree.
    from hklv_extract.extractors import academic_certificate
    from hklv_rules.models import AcademicLevel

    page = make_page(
        ["Daffodil International University", line_text, "& Food Engineering"],
        vl_text="Notary Public\nBachelor of Science in Nutriti",
    )
    level = academic_certificate(PageGroup(kind=PageKind.ACADEMIC_CERTIFICATE, pages=(page,)), "c").level
    assert level.value is AcademicLevel.BACHELOR
    assert level.is_reliable(0.9) is reliable


# --- sample doc 6 (2026-11-12) --------------------------------------------------------------


@pytest.mark.parametrize("with_death_certificate,expected", [(True, Outcome.PASS), (False, Outcome.FAIL)])
def test_frc_deceased_father_named_as_late_needs_no_row(with_death_certificate, expected):
    from builders import FATHER, death, ex

    no_father = tuple(m for m in frc().members if m.relation.value != "FATHER")
    cert = frc(members=no_father).model_copy(update={"late_names": (ex(FATHER),)})
    docs = (cert, death()) if with_death_certificate else (cert,)
    assert by_rule(check_frc(context(*docs)))["FRC-03"].outcome is expected


def test_frc_late_name_is_read_up_to_the_ampersand():
    from hklv_extract.extractors import frc as frc_extract

    page = make_page(["TANGAIL POURASHAVA", "FAMILY CERTIFICATE", "is the son of Late Md", "Abdur Razzak & Rajea Akter and a resident"])
    assert [n.value for n in frc_extract(_group(PageKind.FRC, page), "f").late_names] == ["Md Abdur Razzak"]


def test_bangla_death_certificate_with_an_nid_row_is_a_death_certificate():
    # The title banner is unreadable; the date / cause of death rows are plain text.
    page = make_page(["জাতীয় পরিচয় পত্র নম্বর", "মৃত্যুর তারিখ : ০২-০৬-২০১৭", "মৃত্যুর কারণ : বার্ধক্য"])
    assert classify_page(page, TODAY).kind is PageKind.DEATH_CERTIFICATE


def test_transcript_with_its_title_under_the_stamp_is_a_transcript():
    page = make_page(["BOARD OF INTERMEDIATE AND SECONDARY EDUCATION, DHAKA", "Secondary School Certificate Examination - 2023", "ACADEMIC TRANSCRI", "Sl. No.  Name of Subjects  Letter Grade  Grade Point", "GPA 5.00"])
    assert classify_page(page, TODAY).kind is PageKind.ACADEMIC_TRANSCRIPT


def test_certificate_name_to_the_right_of_certify_that():
    # A tall stamp line once merged rows, so "the next line" was the school's name.
    from hklv_extract.extractors import academic_certificate
    from hklv_ocr.reading import TextLine

    page = make_page(["x"]).model_copy(update={"lines": (
        TextLine(text="ATTESTED stamp", score=0.99, box=(1400, 850, 1900, 1500)),
        TextLine(text="This is to Certify that", score=0.99, box=(690, 930, 1270, 1013)),
        TextLine(text="Tasin Bin Rahad", score=0.99, box=(1360, 928, 1790, 993)),
        TextLine(text="Bindu Basini Govt. Boys' High School", score=0.99, box=(820, 1354, 1770, 1435)),
        TextLine(text="His/Her date of birth as recorded in his / her registration card is Fifth August Two", score=0.99, box=(605, 1781, 2945, 1892)),
        TextLine(text="ATTISTED", score=0.99, box=(1892, 1861, 2179, 1928)),
        TextLine(text="Thousand.", score=0.99, box=(611, 1879, 895, 1953)),
    )})
    cert = academic_certificate(_group(PageKind.ACADEMIC_CERTIFICATE, page), "c")
    assert cert.student_name.value == "Tasin Bin Rahad"
    assert cert.date_of_birth.value == date(2000, 8, 5)


def test_dot_read_as_a_comma_in_a_date():
    from hklv_extract.dates import find_dates

    assert find_dates("Date:25.10,2026") == [date(2026, 10, 25)]
    assert find_dates("Ward 8, 2, 1902") == []


# --- APU RIAD HASAN (2026-11-12, RULES-v3) ---------------------------------------------------


def test_union_parishad_professional_licence_is_a_trade_licence():
    from hklv_extract.extractors import trade_license

    page = make_page([
        "03No Amjhupi Union Parishad",
        "Financial Year: 2026-2027",
        "Licence No: 332  Professional Licence  Date: 08-09-2026",
        "Name of Licences Holder : MD. MOSTAFIZUR RAHAMAN",
    ])
    assert classify_page(page, TODAY).kind is PageKind.TRADE_LICENSE
    assert trade_license(_group(PageKind.TRADE_LICENSE, page), "t").owner_name.value == "MD. MOSTAFIZUR RAHAMAN"


@pytest.mark.parametrize(
    "cell,name",
    [
        ("RIAD HASAN APU. NID NO: 8729747587", "RIAD HASAN APU"),
        ("MD MEHRAB SIAM. DOB-20057187191", "MD MEHRAB SIAM"),
        ("NIDA KHAN", "NIDA KHAN"),
    ],
)
def test_frc_member_id_is_cut_from_the_name_cell(cell, name):
    from hklv_extract.extractors import _CELL_ID

    assert _CELL_ID.sub("", cell) == name


@pytest.mark.parametrize("father,expected", [("MD. KAMAL UDDIN", Outcome.PASS), (None, Outcome.FLAG)])
def test_bilingual_birth_certificate_passes_when_its_english_side_is_complete(father, expected):
    from builders import birth_certificate, ex
    from hklv_rules.models import Extracted, Language
    from hklv_rules.rules import check_birth_certificates

    cert = birth_certificate(language=Language.MIXED, translated=False)
    if father is None:
        cert = cert.model_copy(update={"father_name": Extracted()})
    else:
        cert = cert.model_copy(update={"father_name": ex(father)})
    results = check_birth_certificates(context(cert, with_identity_docs=False))
    assert by_rule(results)["BIRTH-01"].outcome is expected


def test_bdris_registration_number_under_its_heading():
    from hklv_ocr.reading import TextLine

    page = make_page(["x"]).model_copy(update={"lines": (
        TextLine(text="Birth Registration Number", score=1.0, box=(893, 944, 1555, 1003)),
        TextLine(text="Date of Issuance", score=1.0, box=(1810, 945, 2113, 989)),
        TextLine(text="BANGU", score=0.5, box=(171, 988, 258, 1027)),
        TextLine(text="04/03/2017", score=1.0, box=(232, 1015, 434, 1055)),
        TextLine(text="20075718719106516", score=1.0, box=(960, 1007, 1483, 1061)),
        TextLine(text="Date of Birth : 31/12/2007", score=1.0, box=(171, 1150, 900, 1200)),
    )})
    brn = birth_certificate(_group(PageKind.BIRTH_CERTIFICATE, page), "b").registration_number
    assert brn.value == "20075718719106516" and brn.is_reliable(0.9)


@pytest.mark.parametrize("label", ["ame of Student : Riad Hasan Apu", "Name of Srudent : Riad Hasan Apu", "This is to certifg that Riad Hasan Apu"])
def test_student_name_despite_ocr_slips_in_the_label(label):
    from hklv_extract.extractors import academic_transcript

    page = make_page(["BOARD OF INTERMEDIATE AND SECONDARY EDUCATION", label])
    assert academic_transcript(_group(PageKind.ACADEMIC_TRANSCRIPT, page), "t").student_name.value == "Riad Hasan Apu"


# --- AKIBI AL (2026-11-13) ----------------------------------------------------------------


def test_family_certificate_listing_siblings_birth_registration_numbers_is_an_frc():
    page = make_page([
        "NO. 1 DARIAPUR UNION COUNCIL",
        "FAMILY CERTIFICATE",
        "AL ABIBI  YOUNGER BROTHER  11/08/2008  BIRTH REGISTRATION NO: 20085716047020322",
        "01 NO DARIAPUR UNION PARISHAD",
    ])
    assert classify_page(page, TODAY).kind is PageKind.FRC


def test_employment_certificate_on_college_letterhead_is_an_employment_certificate():
    page = make_page([
        "MUJIBNAGAR GOVERNMENT DEGREE COLLEGE",
        "EIIN NO- 118293, National University Code- 0903",
        "EMPLOYMENT CERTIFICATE",
        "This is to certify that Md. Akram Ali is a government employee serving at the College.",
    ])
    assert classify_page(page, TODAY).kind is PageKind.EMPLOYMENT_CERTIFICATE


@pytest.mark.parametrize(
    "line,now",
    [
        ("101329944, is a government employee serving at Mujibnagar Government Degree", True),
        ("position since 26 June 2012 and continues to hold the position to date.", True),
        ("He was a government employee serving at the college until 2020.", False),
    ],
)
def test_current_employment_wording(line, now):
    from hklv_extract.extractors import employment_certificate

    page = make_page(["EMPLOYMENT CERTIFICATE", line])
    assert (employment_certificate(_group(PageKind.EMPLOYMENT_CERTIFICATE, page), "e").currently_employed.value is True) is now


def test_all_caps_father_relation_cell_is_not_a_father_label():
    # A family table row read as the father's name gave FatherRef 'P.S'.
    page = make_page(["Birth Registration Certificate", "MD AKRAM ALI FATHER 01/10/1968 P.S: MUJIBNAGAR"])
    assert birth_certificate(_group(PageKind.BIRTH_CERTIFICATE, page), "b").father_name.value is None


# --- audit 2026-11-14: must-fix findings 1-7 (RULES-v12) ------------------------------------


def test_mrz_name_with_many_filler_words_does_not_hang():
    from hklv_extract.extractors import _agree_with_mrz
    from hklv_rules.models import Extracted

    printed = Extracted[str](value="KKKKKKKKKKKK", confidence=0.95, source_page=1)
    assert _agree_with_mrz(printed, " ".join("K" * 12)) is printed  # 12! orders without the cap


def test_register_ocr_timeout_lets_the_running_ocr_finish(monkeypatch):
    import asyncio
    import threading
    import time

    from hklv_pipeline import pipeline

    finished = threading.Event()

    class SlowReader:
        async def read_file(self, path):
            await asyncio.sleep(0.3)
            finished.set()  # a cancel would stop it here, with the GPU lock already released
            return []

    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    monkeypatch.setattr(pipeline, "REGISTER_OCR_SECONDS", 0.05)
    try:
        with pytest.raises(TimeoutError):
            pipeline.register_reader(SlowReader(), loop)([("page", b"\x89PNG....")])
        assert finished.wait(2)
    finally:
        loop.call_soon_threadsafe(loop.stop)
        time.sleep(0.05)


def test_frc_deceased_father_with_no_late_name_read_flags():
    from builders import death

    no_father = tuple(m for m in frc().members if m.relation.value != "FATHER")
    r = by_rule(check_frc(context(frc(members=no_father), death())))["FRC-03"]
    assert r.outcome is Outcome.FLAG
    assert "no 'Late <name>' read" in r.reason


def test_name_against_a_missing_anchor_is_uncertain_not_a_mismatch():
    from builders import birth_certificate as birth, ex, passport

    from hklv_rules.identity import MatchKind, compare_name
    from hklv_rules.models import Extracted, Person

    ctx = context(passport(), birth().model_copy(update={"father_name": Extracted[str]()}), with_identity_docs=False)
    assert compare_name(ex("MD. ABDUL KARIM"), Person.FATHER, ctx).kind is MatchKind.UNCERTAIN


def test_trade_licence_issued_after_the_check_date_flags():
    from builders import FATHER, ex, trade

    from hklv_rules.rules.trade import check_trade_licenses

    t = trade(FATHER, fiscal_year="2024-2025").model_copy(update={"issue_date": ex(date(2027, 3, 1))})
    r = by_rule(check_trade_licenses(context(t, evaluation_date=date(2027, 1, 15))))["TRADE-03"]
    assert r.outcome is Outcome.FLAG
    assert "after the check date" in r.reason


def test_words_starting_with_a_month_are_not_months():
    from hklv_extract.dates import find_dates

    assert find_dates("Total 75 Marks 2024") == []
    assert find_dates("Class 5 Junior 2019, Janata Bank 12 Janata 2020") == []
    assert find_dates("5 September 2020 and Sept. 6, 2021") == [date(2020, 9, 5), date(2021, 9, 6)]


def test_challan_amount_skips_a_one_digit_serial():
    page = make_page(["Challan No: 2526-0012345678", "Amount", "1", "Total Amount: 10,000"])  # table header, serial
    assert tax_challan(_group(PageKind.TAX_CHALLAN, page), "c").printed_amount.value == Decimal("10000")


# --- RULES-v13: "trade license" inside a sentence is not a trade licence ---------------------


def test_statement_mentioning_a_trade_license_is_not_a_trade_licence():
    page = make_page([
        "STATEMENT OF PURPOSE",
        "Dear Admission Committee,",
        "greatly enhanced my communication, leadership, and analytical presentation skills. Moreover,",
        "since 2021, I have successfully operated my own rod, cement, and construction materials",
        "business under a valid trade license. Managing a commercial enterprise has provided me with",
    ])
    assert classify_page(page, TODAY).kind is not PageKind.TRADE_LICENSE


@pytest.mark.parametrize("title", ["TRADE LICENSE", "Kushtia Pourashava Trade License", "Trade License No: 88103074169", "PROFESSIONAL LICENCE"])
def test_trade_licence_title_on_its_own_line_is_a_trade_licence(title):
    page = make_page(["Government of the People's Republic of Bangladesh", title, "Fiscal Year: 2026-2027"])
    assert classify_page(page, TODAY).kind is PageKind.TRADE_LICENSE


def test_licence_holder_field_counts_inside_a_long_line():
    page = make_page(["Name of Licence Holder MD ABDUL KARIM son of late MD RAHIM of Kushtia Sadar Kushtia"])
    assert classify_page(page, TODAY).kind is PageKind.TRADE_LICENSE


# --- a family certificate citing its affidavit; a CV mentioning bank statements --------------


FAMILY_CERTIFICATE = [
    "FAMILY CERTIFICATE",
    "This is to certify that, according to his submitted documents and affidavit (No.28, Date: 11.10.2026)",
    "the family of KAMAL UDDIN Consists of following members:",
    "S.L Name Relationship Date of Birth NID No",
    "01 KAMAL UDDIN Self 10.05.1997 1234567890",
    "02 ABDUL KARIM Father 28.11.1970 2345678901",
]


def test_family_certificate_citing_its_affidavit_is_an_frc():
    # the issuer only in the Bangla letterhead, read by the layout reader; the English seal unreadable
    page = make_page(FAMILY_CERTIFICATE, vl_text="\n".join(["চট্টগ্রাম সিটি কর্পোরেশন", *FAMILY_CERTIFICATE]))
    assert classify_page(page, TODAY).kind is PageKind.FRC


def test_affidavit_listing_a_family_certificate_stays_an_affidavit():
    page = make_page([
        "AFFIDAVIT",
        "I, KAMAL UDDIN, of Ward 8, Chattogram City Corporation, do hereby solemnly declare",
        "Documents: Passport, Birth Certificate,",
        "Family Certificate",
        "Document's Name | Name | Relation",
        "that KAMAL UDDIN and KAMAL UDDIN MD are the same person.",
    ])
    assert classify_page(page, TODAY).kind is PageKind.AFFIDAVIT


def test_cv_mentioning_bank_statements_is_not_a_statement():
    page = make_page([
        "KAMAL UDDIN",
        "PROFESSIONAL EXPERIENCE",
        "Follow up on payments and reconcile records with bank statements.",
    ])
    assert classify_page(page, TODAY).kind is not PageKind.BANK_STATEMENT


# --- RULES-v14: a name a letter or two off gets a second look, never a FAIL ---------------


def test_near_miss_name_flags_and_a_dropped_title_does_not():
    from builders import ex

    from hklv_rules.identity import MatchKind, compare_name
    from hklv_rules.models import Person

    ctx = context()
    assert compare_name(ex("TANVIR AHMAD"), Person.STUDENT, ctx).kind is MatchKind.UNCERTAIN
    assert compare_name(ex("MD. KAMAL UDDIN"), Person.FATHER, ctx).kind is MatchKind.EXACT
    assert compare_name(ex("KAMAL UDDIN"), Person.FATHER, ctx).kind is MatchKind.MISMATCH  # the title is no letter slip
    assert compare_name(ex("JAMAL HOSSAIN"), Person.FATHER, ctx).kind is MatchKind.MISMATCH


def test_second_reader_confirms_the_reference_spelling():
    from hklv_extract.confidence import text_field
    from hklv_extract.text import Found
    from hklv_rules.identity import MatchKind, compare_name
    from hklv_rules.models import Person

    ctx = context()
    page = make_page(["Name: TANVIR AHMEO"], vl_text="Name: TANVIR AHMED")
    name = text_field(Found("TANVIR AHMEO", 0.99, 1), page)
    assert name.second_read == "TANVIRAHMED"
    assert compare_name(name, Person.STUDENT, ctx).kind is MatchKind.EXACT
    # the line reader has that spelling elsewhere (a sibling's row): no confirmation
    rows = make_page(["TANVIR AHMEO", "TANVIR AHMED"], vl_text="TANVIR AHMED\nTANVIR AHMED")
    assert text_field(Found("TANVIR AHMEO", 0.99, 1), rows).second_read is None

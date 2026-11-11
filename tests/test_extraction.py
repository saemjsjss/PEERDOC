"""Pass 1: confidence from reader agreement, classification, grouping, field extraction.

All names, numbers and MRZ zones are fictional.
"""

from datetime import date

import pytest
from reading_builders import make_page, qr, table_block
from test_mrz import td1, td3

from hklv_extract.build import build_case
from hklv_extract.classify import PageKind, classify_page
from hklv_extract.confidence import AGREE_CAP, DISAGREE, SINGLE_READER_FACTOR, score_text
from hklv_extract.dates import find_dates, parse_date
from hklv_extract.extractors import affidavit, frc, nid, passport, tin_certificate
from hklv_extract.group import group_pages
from hklv_extract.text import Found, find_labeled
from hklv_ocr.reading import CaseReading
from hklv_rules.models.common import Person

TODAY = date(2026, 11, 11)


def groups_for(*pages):
    classes = [classify_page(p, TODAY) for p in pages]
    return group_pages(pages, classes)


# --- confidence -----------------------------------------------------------------------


def test_both_readers_agree_gives_line_score_capped():
    page = make_page(["Name: KAMAL UDDIN"])
    assert score_text(Found("KAMAL UDDIN", 0.999, 1), page) == AGREE_CAP


def test_one_letter_disagreement_drops_below_threshold():
    page = make_page(["Name: KAMAL UDDIN"], vl_text="Name: KAMAL UDDTN")
    assert score_text(Found("KAMAL UDDIN", 0.99, 1), page) == DISAGREE


def test_second_reader_missing_the_field_discounts_the_score():
    page = make_page(["Name: KAMAL UDDIN"], vl_text="Something else entirely")
    assert score_text(Found("KAMAL UDDIN", 0.99, 1), page) == pytest.approx(0.99 * SINGLE_READER_FACTOR)


def test_spacing_differences_still_agree():
    page = make_page(["Name: KAMALUDDIN"], vl_text="Name : Kamal  Uddin")
    assert score_text(Found("KAMALUDDIN", 0.98, 1), page) == 0.98


# --- text helpers ---------------------------------------------------------------------


def test_label_value_on_same_line_and_next_line():
    page = make_page(["Father's Name: ABDUL KARIM", "Mother's Name", "RAHIMA BEGUM"])
    assert find_labeled(page, [r"Father'?s?\s*Name"]).value == "ABDUL KARIM"
    assert find_labeled(page, [r"Mother'?s?\s*Name"]).value == "RAHIMA BEGUM"


def test_value_is_cut_at_the_next_label_on_the_line():
    page = make_page(["Name: KAMAL UDDIN Father: ABDUL KARIM"])
    found = find_labeled(page, [r"Name"], stop_words=[r"Father"])
    assert found.value == "KAMAL UDDIN"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Date: 21/09/2026", date(2026, 9, 21)),
        ("Issued 05-08-2000", date(2000, 8, 5)),
        ("Awarded on: 24 Aug 2026", date(2026, 8, 24)),
        ("30 August, 2026", date(2026, 8, 30)),
        ("August 30, 2026", date(2026, 8, 30)),
        ("2026-01-31", date(2026, 1, 31)),
        ("5th March 1999", date(1999, 3, 5)),
    ],
)
def test_dates_are_day_first(text, expected):
    assert parse_date(text) == expected


def test_two_different_dates_are_not_guessed_between():
    assert parse_date("from 01/01/2026 to 31/03/2026") is None
    assert find_dates("from 01/01/2026 to 31/03/2026") == [date(2026, 1, 1), date(2026, 3, 31)]


def test_impossible_date_is_ignored():
    assert parse_date("31/02/2026") is None


# --- classification -------------------------------------------------------------------


def test_passport_needs_passport_mrz():
    page = make_page(["PEOPLE'S REPUBLIC OF BANGLADESH", "PASSPORT", *td3()])
    assert classify_page(page, TODAY).kind == PageKind.PASSPORT


def test_nid_by_td1_mrz_and_old_nid_by_title():
    assert classify_page(make_page(["NATIONAL ID CARD", *td1()]), TODAY).kind == PageKind.NID
    old = classify_page(make_page(["Government of Bangladesh", "National ID Card", "Name: X"]), TODAY)
    assert old.kind == PageKind.NID and old.mrz is None


def test_frc_needs_issuer_too():
    assert classify_page(make_page(["FAMILY CERTIFICATE", "Some Office"]), TODAY).kind == PageKind.IGNORED
    page = make_page(["03 NO. SAMPLE UNION PARISHAD", "FAMILY CERTIFICATE"])
    assert classify_page(page, TODAY).kind == PageKind.FRC


def test_to_whom_it_may_concern_from_a_university_is_not_a_bank_letter():
    letter = make_page(["SAMPLE UNIVERSITY", "TO WHOM IT MAY CONCERN", "This is to certify that KAMAL UDDIN was a student"])
    assert classify_page(letter, TODAY).kind != PageKind.BANK_SOLVENCY
    bank = make_page(["SAMPLE BANK LTD, Main Branch", "To Whom It May Concern", "A/C No: 0123456789"])
    assert classify_page(bank, TODAY).kind == PageKind.BANK_SOLVENCY


def test_statement_by_transaction_table():
    page = make_page(["SAMPLE BANK", "Date Particulars Debit Credit Balance", "01/01/2026 Opening 0 0 100"])
    assert classify_page(page, TODAY).kind == PageKind.BANK_STATEMENT


def test_tin_and_photo_and_ignored():
    tin = make_page(["National Board of Revenue", "Taxpayer's Identification Number (TIN) Certificate"])
    assert classify_page(tin, TODAY).kind == PageKind.TIN_CERTIFICATE
    assert classify_page(make_page([], from_image_file=True), TODAY).kind == PageKind.PHOTO
    sop = make_page(["STATEMENT OF PURPOSE", "I want to study abroad"])
    assert classify_page(sop, TODAY).kind == PageKind.IGNORED


def test_notarised_translation_is_not_an_affidavit():
    page = make_page(["Notary Public, Whole of Bangladesh", "National ID Card", "Name: KAMAL UDDIN"])
    assert classify_page(page, TODAY).kind == PageKind.NID


# --- grouping -------------------------------------------------------------------------


def test_nid_translation_and_card_group_but_two_people_split():
    a_translation = make_page(["Notary Public", "National ID Card", "NID No: 5551234567", *td1()], page_no=1)
    a_card = make_page(["NATIONAL ID CARD", *td1()], page_no=2)
    b_card = make_page(["NATIONAL ID CARD", *td1(number="7779876543", name="KARIM<<ABDUL")], page_no=3)
    groups = groups_for(a_translation, a_card, b_card)
    assert [g.page_nos for g in groups] == [(1, 2), (3,)]


def test_each_apostille_is_its_own_document():
    pages = [make_page(["e-APOSTILLE", "Convention de La Haye"], page_no=i) for i in (1, 2)]
    assert [g.page_nos for g in groups_for(*pages)] == [(1,), (2,)]


# --- extraction -----------------------------------------------------------------------


def test_passport_fields_from_mrz_and_printed_name_confirmed():
    page = make_page(["PASSPORT", "Surname", "UDDIN", "Given Names", "KAMAL", "Father's Name: ABDUL KARIM", *td3()])
    (g,) = groups_for(page)
    p = passport(g, "passport-1")
    assert p.passport_number.value == "K12345678" and p.passport_number.confidence == 0.99
    assert p.date_of_birth.value == date(1999, 2, 15) and p.date_of_birth.is_reliable(0.9)
    assert (p.surname.value, p.given_names.value) == ("UDDIN", "KAMAL")
    assert p.surname.confidence == AGREE_CAP
    assert (p.mrz_surname.value, p.mrz_given_names.value) == ("UDDIN", "KAMAL")
    assert p.father_name.value == "ABDUL KARIM"


def test_passport_with_broken_mrz_is_not_reliable():
    l1, l2 = td3()
    bad = l2[:14] + ("1" if l2[14] != "1" else "2") + l2[15:]
    (g,) = groups_for(make_page(["PASSPORT", l1, bad]))
    p = passport(g, "passport-1")
    assert not p.date_of_birth.is_reliable(0.9)


def test_nid_card_number_from_mrz_and_translation_number_from_text():
    translation = make_page(
        ["Notary Public", "English Translation", "National ID Card", "Name: RAHIMA BEGUM", "NID No: 5551234567"],
        page_no=1,
        seal=True,
    )
    card = make_page(["NATIONAL ID CARD", "Name", "RAHIMA BEGUM", *td1()], page_no=2)
    (g,) = groups_for(translation, card)
    doc = nid(g, "nid-1")
    assert doc.variant.value == "DIGITAL"
    assert doc.cardholder_name.value == "RAHIMA BEGUM" and doc.cardholder_name.confidence == AGREE_CAP
    assert doc.number_on_card.value == "5551234567"
    assert doc.number_on_translation.value == "5551234567"
    assert doc.has_english_translation.value is True
    assert doc.notary.notary_text_present.value is True
    assert doc.notary.stamp_present.value is True and doc.notary.stamp_present.confidence == 0.95


def test_notarised_card_page_alone_is_not_its_own_translation():
    card = make_page(
        ["NATIONAL ID CARD", "Name: RAHIMA BEGUM", "ID NO: 5551234567", "Notary Public, Whole of Bangladesh"],
        seal=True,
    )
    (g,) = groups_for(card)
    doc = nid(g, "nid-1")
    assert doc.number_on_card.value == "5551234567"
    assert doc.has_english_translation.value is not True
    assert doc.number_on_translation.value is None


def test_every_page_marked_means_no_separate_translation_page():
    a = make_page(["Translated True Copy", "National ID Card", "NID No: 5551234567"], page_no=1)
    b = make_page(["Translated True Copy", "NATIONAL ID CARD", "Name: RAHIMA BEGUM", "NID No: 5551234567"], page_no=2)
    (g,) = groups_for(a, b)
    assert nid(g, "nid-1").number_on_translation.value is None


@pytest.mark.parametrize("marker", ["Translated True Copy", "Authorized to translate", "TrueCopy", "English Version"])
def test_translation_markers_make_a_translation_page(marker):
    translation = make_page(["Notary Public", marker, "National ID Card", "NID No: 5551234567"], page_no=1)
    card = make_page(["NATIONAL ID CARD", "Name", "RAHIMA BEGUM", *td1()], page_no=2)
    (g,) = groups_for(translation, card)
    doc = nid(g, "nid-1")
    assert doc.number_on_translation.value == "5551234567"
    assert doc.has_english_translation.value is True


def test_passport_printed_expiry_read_below_a_garbled_bilingual_label_with_mrz():
    page = make_page(
        ["PASSPORT", "Surname", "UDDIN", "Given Names", "KAMAL",
         "craaacf afiky/Date of Expiry", "es/Holder's Signature", "03JUN2033", *td3(expiry="330603")]
    )
    (g,) = groups_for(page)
    p = passport(g, "passport-1")
    assert p.date_of_expiry.value == date(2033, 6, 3) and p.date_of_expiry.is_reliable(0.9)
    assert p.printed_date_of_expiry.value == date(2033, 6, 3) and p.printed_date_of_expiry.is_reliable(0.9)


def test_passport_printed_expiry_kept_apart_from_a_different_mrz_expiry():
    page = make_page(["PASSPORT", "Date of Expiry", "03JUN2033", *td3()])  # MRZ expiry 01-01-2031
    (g,) = groups_for(page)
    p = passport(g, "passport-1")
    assert p.date_of_expiry.value == date(2031, 1, 1)
    assert p.printed_date_of_expiry.value == date(2033, 6, 3)


def test_passport_without_mrz_takes_the_printed_expiry():
    from hklv_extract.group import PageGroup

    page = make_page(["PASSPORT", "Passport No: K12345678", "Date of Expiry", "03JUN2033"])
    g = PageGroup(kind=PageKind.PASSPORT, pages=[page], classes=[classify_page(page, TODAY)])  # no MRZ read
    p = passport(g, "passport-1")
    assert p.date_of_expiry.value == p.printed_date_of_expiry.value == date(2033, 6, 3)


def test_missing_seal_is_low_confidence_not_a_hard_no():
    page = make_page(["Notary Public", "National ID Card", "Name: RAHIMA BEGUM"])
    (g,) = groups_for(page)
    stamp = nid(g, "nid-1").notary.stamp_present
    assert stamp.value is False and not stamp.is_reliable(0.9)


def test_tin_from_qr():
    page = make_page(
        ["National Board of Revenue", "Taxpayer's Identification Number (TIN) Certificate", "TIN: 123456789012", "1) Name : Kamal Uddin", "2) Father's Name : Abdul Karim"],
        barcodes=[qr("TIN : 123456789012\r\nTaxpayer's Name : Kamal Uddin")],
    )
    (g,) = groups_for(page)
    doc = tin_certificate(g, "tin-1")
    assert doc.taxpayer_name.value == "Kamal Uddin"
    assert doc.tin_printed.value == "123456789012"
    assert doc.qr_decoded and doc.tin_from_qr == "123456789012"


def test_frc_members_from_table():
    page = make_page(
        ["SAMPLE UNION PARISHAD", "FAMILY CERTIFICATE", "KAMAL UDDIN", "ABDUL KARIM", "RAHIMA BEGUM", "Date of Issue: 01/10/2026"],
        blocks=[table_block([["SL", "Name", "Relation"], ["1", "KAMAL UDDIN", "SELF"], ["2", "ABDUL KARIM", "FATHER"], ["3", "RAHIMA BEGUM", "MOTHER"]])],
    )
    (g,) = groups_for(page)
    doc = frc(g, "frc-1")
    assert [(mm.name.value, mm.relation.value) for mm in doc.members] == [
        ("KAMAL UDDIN", "SELF"),
        ("ABDUL KARIM", "FATHER"),
        ("RAHIMA BEGUM", "MOTHER"),
    ]
    assert doc.members[0].name.confidence == AGREE_CAP
    assert doc.issue_date.value == date(2026, 10, 1)
    assert "UNION PARISHAD" in doc.issuer_text.value


def test_affidavit_entries_from_the_two_tables():
    page = make_page(
        ["AFFIDAVIT", "I, KAMAL UDDIN, Father: Abdul Karim, Mother: Rahima Begum", "RAHIMA BEGUM", "RAHIMA", "So, RAHIMA BEGUM and RAHIMA are the same person."],
        blocks=[
            table_block([["Document's Name", "Name", "Relation"], ["Passport, Birth Certificate", "RAHIMA BEGUM", "My Mother's Name"]]),
            table_block([["Document's Name", "Name", "Relation"], ["Mother's NID", "RAHIMA", "My Mother's Name"]]),
        ],
    )
    (g,) = groups_for(page)
    doc = affidavit(g, "affidavit-1")
    assert doc.deponent_name.value == "KAMAL UDDIN"
    assert doc.states_same_person.value is True
    (entry,) = doc.entries
    assert entry.person is Person.MOTHER
    assert (entry.existing_name.value, entry.different_name.value) == ("RAHIMA BEGUM", "RAHIMA")


def test_build_case_end_to_end_runs_the_rules():
    from hklv_rules.engine import evaluate_case

    pages = [
        make_page(["PASSPORT", "Surname", "UDDIN", "Given Names", "KAMAL", *td3()], page_no=1),
        make_page([], page_no=2, from_image_file=True),
        make_page(["STATEMENT OF PURPOSE", "text"], page_no=3),
    ]
    case, report = build_case(CaseReading(pages=tuple(pages)), "fictional", TODAY)
    assert [p.kind for p in report.pages] == [PageKind.PASSPORT, PageKind.PHOTO, PageKind.IGNORED]
    assert [d.kind for d in case.documents] == ["passport", "photo"]
    verdict = evaluate_case(case)
    assert verdict.outcome.value == "FAIL"  # birth certificate, FRC, bank, ... are missing


# --- behaviour found on the real sample set (reproduced with fictional data) ------------


def test_boxed_digits_to_the_right_of_a_label_are_joined():
    from hklv_ocr.reading import TextLine

    label = TextLine(text="Birth Registration No: *", score=0.99, box=(300, 1000, 900, 1060))
    digits = [TextLine(text=c, score=1.0, box=(950 + i * 70, 1002, 990 + i * 70, 1058)) for i, c in enumerate("19990215123456789")]
    page = make_page([]).model_copy(update={"lines": (label, *digits)})
    found = find_labeled(page, [r"Birth\s*Registration\s*No"], value_pattern=r"\d{17}")
    assert found.value == "19990215123456789"


def test_a_far_column_on_the_same_row_is_not_part_of_the_value():
    from hklv_ocr.reading import TextLine

    lines = (
        TextLine(text="Name of Student", score=1.0, box=(100, 500, 500, 540)),
        TextLine(text=": KAMAL UDDIN", score=0.97, box=(600, 500, 1000, 540)),
        TextLine(text="Below 40%", score=1.0, box=(1900, 502, 2200, 540)),
    )
    page = make_page([]).model_copy(update={"lines": lines})
    assert find_labeled(page, [r"Name\s*of\s*Student"]).value == "KAMAL UDDIN"


def test_value_only_the_second_reader_saw_is_kept_but_flagged():
    from hklv_extract.extractors import birth_certificate

    page = make_page(
        ["Office of the Registrar of Birth and Death", "Birth Registration No: *", "Name: Kamal Uddin"],
        vl_text="Birth Registration No: *19990215123456789\nName: Kamal Uddin",
    )
    (g,) = groups_for(page)
    brn = birth_certificate(g, "birth-1").registration_number
    assert brn.value == "19990215123456789" and not brn.is_reliable(0.9)


def test_card_name_without_spaces_takes_the_mrz_word_breaks():
    card = make_page(["NATIONAL ID CARD", "Name", "RAHIMABEGUM", *td1()])
    (g,) = groups_for(card)
    assert nid(g, "nid-1").cardholder_name.value == "RAHIMA BEGUM"


def test_card_name_with_a_different_letter_is_not_changed_to_the_mrz():
    card = make_page(["NATIONAL ID CARD", "Name", "RAHIMA BEGUN", *td1()])
    (g,) = groups_for(card)
    name = nid(g, "nid-1").cardholder_name
    assert name.value == "RAHIMA BEGUN"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("date of birth as recorded is Fifth August Two Thousand.", date(2000, 8, 5)),
        ("is Twenty First March Two Thousand One", date(2001, 3, 21)),
        ("is Thirtieth June Nineteen Ninety Eight", date(1998, 6, 30)),
        ("is Second May One Thousand Nine Hundred Ninety Nine", date(1999, 5, 2)),
        ("is Fifth Augustus Two Thousand", None),
        ("is Thirty Second May Two Thousand", None),
    ],
)
def test_dates_written_in_words(text, expected):
    from hklv_extract.dates import parse_words_date

    assert parse_words_date(text) == expected


def test_ssc_certificate_date_of_birth_in_words_confirmed_by_second_reader():
    from hklv_extract.extractors import academic_certificate

    lines = [
        "SECONDARY SCHOOL CERTIFICATE EXAMINATION, 2015",
        "This is to Certify that",
        "Kamal Uddin",
        "obtained G.P.A 5.00 on a scale of 5.00",
        "His/Her date of birth as recorded in his / her registration card is Fifteenth February",
        "Nineteen Ninety Nine.",
    ]
    (g,) = groups_for(make_page(["e-APOSTILLE"], page_no=1), make_page(lines, page_no=2))[1:]
    doc = academic_certificate(g, "cert-1")
    assert doc.level.value.value == "SSC"
    assert doc.student_name.value == "Kamal Uddin"
    assert doc.date_of_birth.value == date(1999, 2, 15) and doc.date_of_birth.is_reliable(0.9)


def test_academic_level_is_the_highest_named():
    from hklv_extract.extractors import academic_transcript

    page = make_page(
        ["SAMPLE UNIVERSITY", "ACADEMIC TRANSCRIPT", "Admission: HSC (HIGHER SECONDARY CERTIFICATE EXAMINATION) OR EQUIVALENT", "Degree: BACHELOR OF BUSINESS ADMINISTRATION"],
        page_no=2,
    )
    (g,) = groups_for(make_page(["e-APOSTILLE"], page_no=1), page)[1:]
    assert academic_transcript(g, "t-1").level.value.value == "BACHELOR"


def test_academic_pages_count_only_inside_an_apostille_block():
    from hklv_extract.classify import classify_pages

    cert = ["SAMPLE UNIVERSITY", "This is to certify that KAMAL UDDIN obtained the degree"]
    pages = [
        make_page(cert, page_no=1),  # a recommendation letter: no apostille before it
        make_page(["e-APOSTILLE", "Convention de La Haye"], page_no=2),
        make_page(cert, page_no=3),
        make_page(["STATEMENT OF PURPOSE"], page_no=4),
        make_page(cert, page_no=5),  # block ended at the ignored page
    ]
    kinds = [c.kind for c in classify_pages(pages, TODAY)]
    assert kinds == [PageKind.IGNORED, PageKind.E_APOSTILLE, PageKind.ACADEMIC_CERTIFICATE, PageKind.IGNORED, PageKind.IGNORED]


def test_words_shared_between_document_types_do_not_misclassify():
    trade = make_page(["TRADE LICENSE", "Name of Proprietor: ABDUL KARIM", "NID/Passport/ Birth Certificate", "Birth Registration No: 1"])
    assert classify_page(trade, TODAY).kind == PageKind.TRADE_LICENSE
    birth = make_page(["Office of the Registrar of Birth and Death", "Birth Certificate", "Birth Registration No: 19990215123456789"])
    assert classify_page(birth, TODAY).kind == PageKind.BIRTH_CERTIFICATE
    tin = make_page(["National Board of Revenue", "Taxpayer's Identification Number (TIN) Certificate", "1. A Taxpayer is liable to file the Return of Income"])
    assert classify_page(tin, TODAY).kind == PageKind.TIN_CERTIFICATE
    affidavit_page = make_page(["AFFIDAVIT", "Passport, Birth Certificate", "Mother's NID No: 5551234567"])
    assert classify_page(affidavit_page, TODAY).kind == PageKind.AFFIDAVIT
    frc_page = make_page(["SAMPLE UNION PARISHAD", "Family Certificate", "NID NO/ BIRTH CERTIFICATE"])
    assert classify_page(frc_page, TODAY).kind == PageKind.FRC
    original = make_page(["unreadable"], barcodes=[qr("https://example.gov/verify/trade_bn/123")])
    assert classify_page(original, TODAY).kind == PageKind.TRADE_LICENSE


def test_nid_pages_without_mrz_split_by_printed_number_but_tolerate_a_typo():
    father_tr = make_page(["Notary Public", "National ID Card", "NID No: 5551234567"], page_no=1)
    father_card = make_page(["NATIONAL ID CARD", *td1()], page_no=2)
    mother_tr = make_page(["Notary Public", "National ID Card", "NID No: 7779876543"], page_no=3)
    mother_card = make_page(["NATIONAL ID CARD", "NID No: 7779876548"], page_no=4)  # 1-digit typo: same card
    groups = groups_for(father_tr, father_card, mother_tr, mother_card)
    assert [g.page_nos for g in groups] == [(1, 2), (3, 4)]


def test_seal_next_to_notary_text_is_confirmed_a_far_or_weak_one_is_not():
    from hklv_extract.common_fields import notary_info
    from hklv_ocr.reading import LayoutBlock

    base = make_page(["National ID Card", "Name: RAHIMA BEGUM", "Notary Public, Whole of Bangladesh"])
    notary_line = base.lines[-1]
    near = LayoutBlock(label="seal", text="", box=(notary_line.box[0], notary_line.box[3] + 50, notary_line.box[0] + 300, notary_line.box[3] + 350), score=0.62)
    far = near.model_copy(update={"box": (2000, 3200, 2300, 3450)})
    weak = near.model_copy(update={"score": 0.3})
    for seal, reliable in ((near, True), (far, False), (weak, False)):
        page = base.model_copy(update={"blocks": (*base.blocks, seal)})
        assert notary_info([page]).stamp_present.is_reliable(0.9) is reliable


def test_ielts_test_report_form_is_extracted():
    from hklv_extract.extractors import language_test

    page = make_page(
        [
            "IELTS",
            "Test Report Form",
            "Date 12/OCT/2026",
            "Family Name: UDDIN",
            "First Name: KAMAL",
            "Date of Birth 15/02/1999",
        ],
        page_no=1,
    )
    (g,) = groups_for(page)
    assert g.kind == PageKind.LANGUAGE_TEST
    doc = language_test(g, "language_test-1")
    assert doc.test.value.value == "IELTS"
    assert doc.candidate_name.value == "KAMAL UDDIN" and doc.candidate_name.is_reliable(0.9)
    assert doc.date_of_birth.value == date(1999, 2, 15)
    assert doc.test_date.value == date(2026, 10, 12)


def test_language_test_reaches_the_case_file():
    case, _ = build_case(CaseReading(pages=(make_page(["TOPIK", "Name: KAMAL UDDIN", "Date of Birth: 15/02/1999", "Date of Issue: 01/06/2026"]),)), "c", TODAY)
    (doc,) = case.documents
    assert doc.kind == "language_test" and doc.test.value.value == "TOPIK"
    assert doc.candidate_name.value == "KAMAL UDDIN" and doc.test_date.value == date(2026, 6, 1)


@pytest.mark.parametrize(
    "seal_text,reliable",
    [
        ("ADVOCATE MD SAMPLE NAME\nNOTARY PUBLIC\nWHOLE OF BANGLADESH", True),
        ("ADVOCATE MD SAMPLE NAME\nNOTARY PULIC", True),  # misread "PUBLIC", stems survive
        ("NOTARYY PUBLIC\nGOVT.OF BANGLADESH", True),
        ("GOVERNMENT OF THE PEOPLE'S REPUBLIC OF BANGLADESH", False),  # an emblem, not a notary
        ("\u4e2d\u534e\u4eba\u6c11", False),  # made-up text from the VL model
    ],
)
def test_seal_is_confirmed_by_its_own_ring_text(seal_text, reliable):
    from hklv_extract.common_fields import notary_info
    from hklv_ocr.reading import LayoutBlock

    # Notary wording printed right next to the seal must NOT rescue a seal whose own text
    # says something else: the seal's text decides when it was read.
    base = make_page(["National ID Card", "Notary Public, Whole of Bangladesh"])
    line = base.lines[-1]
    seal = LayoutBlock(label="seal", text=seal_text, box=(line.box[0], line.box[3] + 20, line.box[0] + 300, line.box[3] + 320), score=0.82)
    page = base.model_copy(update={"blocks": (*base.blocks, seal)})
    assert notary_info([page]).stamp_present.is_reliable(0.9) is reliable


# --- bank solvency holder ---------------------------------------------------------------


@pytest.mark.parametrize(
    "sentence,expected",
    [
        # 'Md' / 'Mst' are part of the name (MD X != X under the name policy): kept.
        ("This is to certify that Md Kamal Uddin, Father's Name: Md. Abdul Karim", "Md Kamal Uddin"),
        ("This is to certify that Md. Kamal Uddin, Son of Abdul Karim", "Md. Kamal Uddin"),
        ("This is to certify that Mst. Rahima Begum, Wife of Abdul Karim", "Mst. Rahima Begum"),
        # Courtesy titles are not: dropped.
        ("This is to certify that Mr. Kamal Uddin, Son of Abdul Karim", "Kamal Uddin"),
        ("This is to certify that Mrs Rahima Begum has been maintaining an account", "Rahima Begum"),
    ],
)
def test_solvency_holder_keeps_md_and_mst_but_drops_courtesy_titles(sentence, expected):
    from hklv_extract.extractors import bank_solvency
    from hklv_extract.group import PageGroup

    page = make_page(["SAMPLE BANK PLC", "SOLVENCY CERTIFICATE", sentence])
    holder = bank_solvency(PageGroup(kind=PageKind.BANK_SOLVENCY, pages=[page]), "solvency-1").account_holder
    assert holder.value == expected


def test_solvency_holder_with_md_matches_the_father_spelled_md():
    from hklv_rules.names import names_equal

    assert names_equal("Md Kamal Uddin", "MD KAMAL UDDIN")
    assert not names_equal("Kamal Uddin", "MD KAMAL UDDIN")  # why the prefix must not be stripped


# --- bank account number in a details table ----------------------------------------------
# A fictional solvency letter laid out like a real one: the number sits two rows below an
# "Account Number" header, beside other headers, under a two-row merged header.

from hklv_ocr.reading import LayoutBlock, TextLine  # noqa: E402

ACCOUNT = "0123456789012"
LETTER_TABLE = (
    "<table>"
    '<tr><td rowspan="2">Sl. No.</td><td colspan="3">Account</td><td colspan="2">Balance</td></tr>'
    "<tr><td>Account Number</td><td>Open Date</td><td>Account Type</td><td>(BDT)</td><td>Equivalent (USD)</td></tr>"
    f"<tr><td>1</td><td>{ACCOUNT}</td><td>05 October, 2026</td><td>Savings Bank Account</td><td>12,34,500.00</td><td>9,876.54</td></tr>"
    '<tr><td colspan="4">Total</td><td>12,34,500.00</td><td>9,876.54</td></tr>'
    "</table>"
)


def _line(text, x0, y0, x1, score=0.99):
    return TextLine(text=text, score=score, box=(x0, y0, x1, y0 + 40))


def _letter(header_row, data_rows, *, table=LETTER_TABLE):
    lines = [
        _line("SAMPLE BANK PLC", 100, 100, 800),
        _line("SOLVENCY CERTIFICATE", 100, 200, 900),
        _line("This is to certify that Md Kamal Uddin, Father's Name: Md. Abdul Karim", 100, 400, 2300),
        *header_row,
        *(ln for row in data_rows for ln in row),
        _line("Date: 29 October, 2026", 1800, 1400, 2300),
    ]
    page = make_page([]).model_copy(update={"lines": tuple(lines)})
    # PaddleOCR-VL sees the prose as text and the details as the table, as on a real page.
    in_table = {id(ln) for ln in (*header_row, *(ln for row in data_rows for ln in row))}
    prose = [ln.text for ln in lines if id(ln) not in in_table]
    text = LayoutBlock(label="text", text="\n".join(prose), box=(90, 90, 2400, 1500))
    blocks = (text, LayoutBlock(label="table", text=table, box=(100, 780, 2300, 1100))) if table else (text,)
    return page.model_copy(update={"blocks": blocks})


HEADERS = [
    _line("Sl. No.", 150, 800, 300),
    _line("Account Number", 400, 800, 700),
    _line("Open Date", 800, 800, 1000),
    _line("Account Type", 1100, 800, 1400),
    _line("(BDT)", 1500, 800, 1650),
    _line("Equivalent (USD)", 1800, 800, 2100),
]
MERGED_HEADER = [_line("Sl. No. Account Number Open Date Account Type (BDT) Equivalent (USD)", 150, 800, 2100)]


def _row(y, number):
    return [
        _line("1", 200, y, 230),
        _line(number, 420, y, 690),
        _line("05 October, 2026", 790, y, 1020),
        _line("Savings Bank Account", 1080, y, 1420),
        _line("12,34,500.00", 1500, y, 1700),
    ]


def _solvency(page):
    from hklv_extract.extractors import bank_solvency
    from hklv_extract.group import PageGroup

    return bank_solvency(PageGroup(kind=PageKind.BANK_SOLVENCY, pages=[page]), "solvency-1")


def test_table_grid_expands_merged_cells():
    from hklv_extract.extractors import _table_grid

    grid = _table_grid(LETTER_TABLE)
    assert grid[1][0] == "Sl. No"  # the two-row cell fills the second header row too (cells are cleaned)
    assert grid[1][1] == "Account Number" and grid[2][1] == ACCOUNT  # same column index
    assert grid[3][:4] == ["Total"] * 4


def test_table_grid_caps_absurd_spans():
    from hklv_extract.extractors import MAX_SPAN, _table_grid

    assert len(_table_grid('<table><tr><td rowspan="99999999">x</td></tr></table>')) == MAX_SPAN


def test_solvency_account_number_below_its_column_header():
    sol = _solvency(_letter(HEADERS, [_row(900, ACCOUNT)]))
    assert sol.account_number.value == ACCOUNT
    assert sol.account_number.confidence == FALLBACK_MAX  # evidence for the reviewer: FLAG
    assert sol.account_holder.value == "Md Kamal Uddin"


def test_solvency_account_number_from_the_vl_table_when_headers_run_together():
    # PP-OCRv6 read the header row as one line, so no line is just "Account Number"; the
    # labelled lookup (unchanged) takes the number on the next line, both readers agree.
    sol = _solvency(_letter(MERGED_HEADER, [_row(900, ACCOUNT)]))
    assert sol.account_number.value == ACCOUNT
    assert sol.account_number.is_reliable(0.9)


def test_vl_only_account_number_stays_below_threshold():
    row = [ln for ln in _row(900, ACCOUNT) if ln.text != ACCOUNT]  # PP-OCRv6 missed the number
    sol = _solvency(_letter(MERGED_HEADER, [row]))
    assert sol.account_number.value == ACCOUNT
    assert not sol.account_number.is_reliable(0.9)


def test_several_different_accounts_in_the_column_are_not_guessed():
    other = "0987654321098"
    table = LETTER_TABLE.replace(
        '<tr><td colspan="4">Total',
        f"<tr><td>2</td><td>{other}</td><td>01 May, 2025</td><td>Current Account</td><td>1.00</td><td>0.01</td></tr>"
        '<tr><td colspan="4">Total',
    )
    sol = _solvency(_letter(HEADERS, [_row(900, ACCOUNT), _row(980, other)], table=table))
    assert sol.account_number.value is None


def test_value_in_another_column_is_not_taken():
    # Digits sit only under "Open Date"; nothing under "Account Number".
    row = [_line("1", 200, 900, 230), _line("0510 2026 111", 800, 900, 1000)]
    sol = _solvency(_letter(HEADERS, [row], table=None))
    assert sol.account_number.value is None


def test_labelled_account_number_still_comes_first():
    page = make_page(["SAMPLE BANK PLC", "SOLVENCY CERTIFICATE", "A/C No: 5555 6666 7777"])
    assert _solvency(page).account_number.value == "555566667777"


# Review findings: a column value must never come out confidently wrong. Each of these
# returned a wrong number at 0.99 before; BANK-02 would then FAIL a correct case.

WRAPPED_HEADER = [_line("Sl. No.", 150, 780, 300), _line("Account", 450, 780, 650), _line("Number", 450, 825, 650)]


def test_number_wrapped_onto_two_lines_is_not_cut_short():
    long_no = "20501234567890123"
    table = LETTER_TABLE.replace(ACCOUNT, long_no)
    row = [_line("1", 200, 900, 230), _line("2050123456789", 420, 900, 690), _line("0123", 420, 945, 520)]
    acct = _solvency(_letter(HEADERS, [row], table=table)).account_number
    assert not (acct.value == "2050123456789" and acct.is_reliable(0.9))
    assert not acct.is_reliable(0.9)  # the full number is only in the VL cell: FLAG


def test_line_joined_with_the_serial_number_cell_is_not_taken_whole():
    row = [_line("1 " + ACCOUNT, 200, 900, 690), _line("05 October, 2026", 790, 900, 1020)]
    acct = _solvency(_letter(HEADERS, [row])).account_number
    assert acct.value == ACCOUNT and not acct.is_reliable(0.9)  # only the VL cell is usable: FLAG


def test_line_joined_with_a_numeric_date_cell_is_not_taken_whole():
    row = [_line("1", 200, 900, 230), _line(ACCOUNT + " 05-10-2026", 420, 900, 1000)]
    acct = _solvency(_letter(HEADERS, [row])).account_number
    assert acct.value == ACCOUNT and not acct.is_reliable(0.9)


def test_vl_cell_missing_a_digit_is_not_confirmed_by_the_longer_number():
    table = LETTER_TABLE.replace(ACCOUNT, ACCOUNT[1:])  # VL dropped the leading zero
    acct = _solvency(_letter(WRAPPED_HEADER, [_row(900, ACCOUNT)], table=table)).account_number
    assert acct.value == ACCOUNT[1:]
    assert not acct.is_reliable(0.9)  # the readers disagree: FLAG, never FAIL


def test_dashed_vl_misread_is_not_confirmed_piece_by_piece():
    vl_no, ocr_no = "0123-456789-01", "0123-456789-07"
    table = LETTER_TABLE.replace(ACCOUNT, vl_no)
    row = [_line("1", 200, 900, 230), _line(ocr_no, 420, 900, 690), _line("01 May, 2025", 790, 900, 1020)]
    acct = _solvency(_letter(MERGED_HEADER, [row], table=table)).account_number
    assert not acct.is_reliable(0.9)


def test_masked_number_under_the_header_stops_the_column_search():
    lines = [
        _line("Account Number", 400, 800, 700),
        _line("XXXX-XXXX-9012", 420, 900, 690),
        _line("Customer ID", 420, 1000, 690),
        _line("88776655", 420, 1100, 690),
    ]
    acct = _solvency(_letter(lines, [], table=None)).account_number
    assert acct.value is None


def test_number_agreed_by_both_readers_is_reliable_and_numbers_never_match_inside_longer_ones():
    from hklv_extract.extractors import _digit_runs

    assert "0123456789012" in _digit_runs("1 0123456789012")
    assert "123456789012" not in _digit_runs("0123456789012")
    assert "012345678901" in _digit_runs("A/C 0123-456789-01")


# --- older City Corporation birth certificates (BDR Form-3), fictional ----------------------
# Title "Birth Registration Certificate" (often in a decorative font), "BR Number" with one
# digit per box, the date of birth in boxes and again in words, parents' BRN and NID.


def _old_birth_page(title="Birth Registration Certificate", brn="2 0 0 1 0 2 1 5 1 2 3 4 5 6 7 8 9", dob="05 08 2001"):
    return make_page(
        [
            "Government of the People's Republic of Bangladesh",
            "Office of the Birth and Death Registrar",
            "City Corporation: Sample City Corporation",
            title,
            "Register No. 12",
            f"BR Number: {brn}",
            "Name: KAMAL UDDIN",
            f"Date of Birth: {dob}",
            "In Word: 5th August, 2001",
            "Father's Name: MD ABDUL KARIM",
            "Father's BRN: 19701234567890123",
            "Father's NID: 1234567890",
            "Mother's Name: MST RAHIMA BEGUM",
            # Last, so the lines above keep their positions (some tests insert rows between them).
            "Date of Registration: 11/04/2002",
            "Order of Child: 1",
        ]
    )


def test_old_style_birth_certificate_is_recognised_by_its_title():
    assert classify_page(_old_birth_page(), TODAY).kind == PageKind.BIRTH_CERTIFICATE


def test_old_style_birth_certificate_with_a_garbled_title_is_recognised_by_its_fields():
    c = classify_page(_old_birth_page(title="Birfh Regiftration Certifcate"), TODAY)
    assert c.kind == PageKind.BIRTH_CERTIFICATE
    assert "BR Number" in c.reason


def test_family_certificate_listing_brns_stays_a_family_certificate():
    page = make_page(
        [
            "Sample Union Parishad",
            "FAMILY CERTIFICATE",
            "Office of the Birth and Death Registrar",
            "Name: KAMAL UDDIN  Relation: Self  BRN: 20010215123456789  Date of Birth: 05/08/2001",
        ]
    )
    assert classify_page(page, TODAY).kind == PageKind.FRC


def test_brn_and_date_of_birth_without_a_registrar_office_are_not_a_birth_certificate():
    page = make_page(["SAMPLE COLLEGE", "Student's BRN: 20010215123456789", "Date of Birth: 05/08/2001"])
    assert classify_page(page, TODAY).kind != PageKind.BIRTH_CERTIFICATE


def _old_birth(page):
    from hklv_extract.extractors import birth_certificate

    (g,) = groups_for(page)
    assert g.kind == PageKind.BIRTH_CERTIFICATE
    return birth_certificate(g, "birth-1")


def test_old_style_birth_certificate_fields():
    cert = _old_birth(_old_birth_page())
    assert cert.registration_number.value == "20010215123456789"  # all 17 boxed digits
    assert cert.registration_number.confidence == FALLBACK_MAX  # "BR Number" fallback: FLAG
    assert cert.date_of_birth.value == date(2001, 8, 5)  # boxed DOB, day first
    assert cert.date_of_birth.confidence == FALLBACK_MAX
    assert cert.name.value == "KAMAL UDDIN"
    assert cert.father_name.value == "MD ABDUL KARIM"


def test_brn_longer_than_twenty_digits_is_not_cut_to_fit():
    cert = _old_birth(_old_birth_page(brn="2 0 0 1 0 2 1 5 1 2 3 4 5 6 7 8 9 1 2 3 4"))
    assert cert.registration_number.value is None


def test_date_of_birth_in_words_is_used_when_the_boxes_are_unreadable():
    cert = _old_birth(_old_birth_page(dob="# #"))
    assert cert.date_of_birth.value == date(2001, 8, 5)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("08 05 2006", date(2006, 5, 8)),
        ("0 8 0 5 2 0 0 6", date(2006, 5, 8)),
        ("08052006", date(2006, 5, 8)),
        ("20060508", date(2006, 5, 8)),  # only valid as YYYYMMDD
        ("19121912", date(1912, 12, 19)),  # both readings give the same date
        ("0805206", None),
        ("08 05 20066", None),
        ("31 02 2006", None),
        ("08/05/2006", None),  # not boxed: parse_date's job
    ],
)
def test_parse_boxed_date(text, expected):
    from hklv_extract.dates import parse_boxed_date

    assert parse_boxed_date(text) == expected


# Review round 2: a value from PaddleOCR-VL's table alone is never confident, and a VL column
# that does not line up with its header decides nothing.

CUSTOMER_HEADERS = [
    _line("Sl. No.", 150, 800, 300),
    _line("Account Number", 400, 800, 700),
    _line("Customer ID", 800, 800, 1000),
    _line("Account Type", 1100, 800, 1400),
]


def test_vl_row_shifted_left_does_not_put_the_customer_id_under_account_number():
    table = (
        "<table><tr><td>Sl. No.</td><td>Account Number</td><td>Customer ID</td><td>Account Type</td></tr>"
        f"<tr><td>1 {ACCOUNT}</td><td>88776655</td><td>Savings Bank Account</td></tr></table>"
    )
    row = [_line("1 " + ACCOUNT, 200, 900, 690), _line("88776655", 800, 900, 1000)]
    acct = _solvency(_letter(CUSTOMER_HEADERS, [row], table=table)).account_number
    assert acct.value != "88776655"
    assert not acct.is_reliable(0.9)


def test_serial_number_joined_by_both_readers_is_not_confident():
    table = LETTER_TABLE.replace(f"<tr><td>1</td><td>{ACCOUNT}</td>", f"<tr><td></td><td>1 {ACCOUNT}</td>")
    row = [_line("1 " + ACCOUNT, 200, 900, 690), _line("05 October, 2026", 790, 900, 1020)]
    acct = _solvency(_letter(HEADERS, [row], table=table)).account_number
    assert not acct.is_reliable(0.9)


def test_second_account_beyond_the_line_window_still_makes_the_column_unclear():
    other = "0987654321098"
    table = LETTER_TABLE.replace(
        '<tr><td colspan="4">Total',
        f"<tr><td>2</td><td>{other}</td><td>01 May, 2025</td><td>Current Account</td><td>1.00</td><td>0.01</td></tr>"
        '<tr><td colspan="4">Total',
    )
    far = 840 + 700  # past COLUMN_MAX_DROP_PX below the header
    acct = _solvency(_letter(HEADERS, [_row(900, ACCOUNT), _row(far, other)], table=table)).account_number
    assert not acct.is_reliable(0.9)


@pytest.mark.parametrize(
    "data_row",
    [
        f"<tr><td>{ACCOUNT}</td><td>8877665544</td><td>05 October, 2026</td></tr>",  # serial cell left out
        f"<tr><td/><td>{ACCOUNT}</td><td>8877665544</td><td>05 October, 2026</td></tr>",  # self-closed cell
        f"<tr><td><td>{ACCOUNT}</td><td>8877665544</td><td>05 October, 2026</td></tr>",  # unclosed cell
    ],
)
def test_vl_row_that_does_not_line_up_with_its_header_decides_nothing(data_row):
    table = "<table><tr><td>Sl. No.</td><td>Account Number</td><td>Customer ID</td><td>Open Date</td></tr>" + data_row + "</table>"
    row = [_line(ACCOUNT, 420, 900, 690), _line("8877665544", 800, 900, 1000)]
    acct = _solvency(_letter(WRAPPED_HEADER, [row], table=table)).account_number
    assert acct.value != "8877665544"
    assert not acct.is_reliable(0.9)


def test_absurd_span_values_do_not_crash():
    from hklv_extract.extractors import MAX_SPAN, _table_grid

    assert _table_grid('<table><tr><td colspan="' + "9" * 5000 + '">x</td></tr></table>') == [["x"] * MAX_SPAN]


# Review: "Birth Registration Certificate" names the document in other documents too.


@pytest.mark.parametrize(
    "lines,kind",
    [
        (
            ["English Translation", "No. 5 Sample Union Parishad", "Family Certificate",
             "This is to certify that the following persons are members of the same family.",
             "SL  Name  Relation  Birth Registration Certificate No. / NID No.",
             "1  KAMAL UDDIN  Self  20010215123456789"],
            PageKind.FRC,
        ),
        (
            ["Sample Union Parishad", "FAMILY CERTIFICATE",
             "This certificate is issued on the basis of their NID / Birth Registration Certificate.",
             "Name  Relation  Date of Birth", "KAMAL UDDIN  Self  05/08/2001"],
            PageKind.FRC,
        ),
        (
            ["To", "The Visa Officer", "Subject: Submission of documents", "Dear Sir,",
             "Please find enclosed the following documents:", "1. Passport copy",
             "2. Birth Registration Certificate (with English translation)", "3. Photograph",
             "Yours faithfully", "Kamal Uddin"],
            PageKind.IGNORED,
        ),
        (["Birth Registration Certificate"], PageKind.IGNORED),  # a title and nothing else
    ],
)
def test_birth_registration_certificate_named_elsewhere_is_not_a_birth_certificate(lines, kind):
    assert classify_page(make_page(lines), TODAY).kind == kind


def test_registrar_and_date_of_birth_need_two_birth_only_fields():
    page = make_page(["Office of the Birth and Death Registrar", "Birth Registration Certificate", "Name: KAMAL UDDIN", "Date of Birth: 05/08/2001"])
    assert classify_page(page, TODAY).kind != PageKind.BIRTH_CERTIFICATE
    page = make_page(["Office of the Birth and Death Registrar", "Name: KAMAL UDDIN", "Date of Birth: 05/08/2001",
                      "Register No. 12", "Date of Registration: 11/04/2002"])
    c = classify_page(page, TODAY)
    assert c.kind == PageKind.BIRTH_CERTIFICATE and "Date of Registration" in c.reason


# Final review round.


@pytest.mark.parametrize(
    "lines",
    [
        ["To", "The Visa Officer", "Applicant: KAMAL UDDIN", "Date of Birth: 05/08/2001",
         "Please find enclosed the following documents:", "1. Passport copy",
         "2. Birth Registration Certificate", "3. Photograph", "Yours faithfully"],
        ["Name: KAMAL UDDIN, Date of Birth: 05/08/2001", "Enclosures:", "Birth Registration Certificate"],
        ["Checklist", "[x] Birth Registration Certificate", "Father's BRN: 19701234567890123"],
    ],
)
def test_cover_letters_and_checklists_naming_the_certificate_are_not_one(lines):
    assert classify_page(make_page(lines), TODAY).kind != PageKind.BIRTH_CERTIFICATE


def test_old_style_fields_seen_only_by_the_second_reader_still_count():
    lines = ["Sample City Corporation", "Name: KAMAL UDDIN"]
    vl = "\n".join([*lines, "Office of the Birth and Death Registrar", "BR Number: 20010215123456789",
                    "Date of Birth: 05/08/2001", "Order of Child: 1"])
    assert classify_page(make_page(lines, vl_text=vl), TODAY).kind == PageKind.BIRTH_CERTIFICATE


def test_in_word_fallback_reads_only_its_own_line():
    page = _old_birth_page(dob="# #")
    lines = [ln for ln in page.lines if not ln.text.startswith("In Word")]
    words = TextLine(text="In Word: Fifth August Two Thousand One", score=0.99, box=(100, 2000, 1500, 2040))
    reg = TextLine(text="Date of Registration: 12/09/2001", score=0.99, box=(100, 2060, 1500, 2100))
    page = page.model_copy(update={"lines": (*lines, words, reg)})
    page = page.model_copy(update={"blocks": (LayoutBlock(label="text", text=page.line_text, box=(0, 0, 2400, 2200)),)})
    assert _old_birth(page).date_of_birth.value == date(2001, 8, 5)

    unreadable = words.model_copy(update={"text": "In Word: ####"})
    page = page.model_copy(update={"lines": (*lines, unreadable, reg)})
    assert _old_birth(page).date_of_birth.value is None  # never the registration date


TX_HEADERS = [
    _line("Date", 150, 800, 300),
    _line("Particulars", 350, 800, 600),
    _line("Account Number", 650, 800, 950),
    _line("Debit", 1000, 800, 1150),
    _line("Credit", 1200, 800, 1350),
    _line("Balance", 1400, 800, 1550),
]
TX_TABLE = (
    "<table><tr><td>Date</td><td>Particulars</td><td>Account Number</td><td>Debit</td><td>Credit</td><td>Balance</td></tr>"
    "<tr><td>01-10-2026</td><td>Fund Transfer</td><td>2059876543210</td><td></td><td>50,000.00</td><td>1,50,000.00</td></tr></table>"
)
TX_ROW = [
    _line("01-10-2026", 150, 900, 300),
    _line("Fund Transfer", 350, 900, 600),
    _line("2059876543210", 660, 900, 940),
    _line("50,000.00", 1200, 900, 1350),
]


def _statement(holder_line):
    from hklv_extract.extractors import bank_statement
    from hklv_extract.group import PageGroup

    lines = [_line("SAMPLE BANK PLC", 100, 100, 800), _line("STATEMENT OF ACCOUNT", 100, 200, 900), holder_line, *TX_HEADERS, *TX_ROW]
    page = make_page([]).model_copy(update={"lines": tuple(lines)})
    prose = "\n".join(ln.text for ln in lines[:3])
    page = page.model_copy(
        update={"blocks": (LayoutBlock(label="text", text=prose, box=(0, 0, 2400, 700)), LayoutBlock(label="table", text=TX_TABLE, box=(100, 780, 2300, 1000)))}
    )
    return bank_statement(PageGroup(kind=PageKind.BANK_STATEMENT, pages=[page]), "statement-1")


@pytest.mark.parametrize(
    "holder",
    [
        "Account No: XXXXXXXXX7001",  # masked holder number
        "Acc. No.: 1501234567001",  # a label the lookup does not know
    ],
)
def test_transaction_table_account_column_is_never_the_holders_account(holder):
    acct = _statement(_line(holder, 100, 400, 1200)).account_number
    assert acct.value != "2059876543210"
    assert acct.value is None


# Review round 4.


def test_wrapped_transaction_headers_still_mark_the_table_as_transactions():
    from hklv_extract.extractors import bank_statement
    from hklv_extract.group import PageGroup

    headers = [
        _line("Date", 150, 820, 300),
        _line("Particulars of", 350, 800, 600), _line("Transaction", 350, 845, 600),
        _line("Account Number", 650, 820, 950),
        _line("Withdrawal", 1000, 800, 1150), _line("Amount", 1000, 845, 1150),
        _line("Deposit", 1200, 800, 1350), _line("Amount", 1200, 845, 1350),
        _line("Balance", 1400, 820, 1550),
    ]
    table = (
        "<table><tr><td>Date</td><td>Particulars of Transaction</td><td>Account Number</td>"
        "<td>Withdrawal Amount</td><td>Deposit Amount</td><td>Balance</td></tr>"
        "<tr><td>01-10-2026</td><td>Fund Transfer</td><td>2059876543210</td><td></td><td>50,000.00</td><td>1,50,000.00</td></tr></table>"
    )
    row = [_line("01-10-2026", 150, 950, 300), _line("Fund Transfer", 350, 950, 600), _line("2059876543210", 660, 950, 940)]
    lines = [_line("SAMPLE BANK PLC", 100, 100, 800), _line("STATEMENT OF ACCOUNT", 100, 200, 900),
             _line("Acc. No.: 1501234567001", 100, 400, 1200), *headers, *row]
    page = make_page([]).model_copy(update={"lines": tuple(lines)})
    page = page.model_copy(update={"blocks": (
        LayoutBlock(label="text", text="\n".join(ln.text for ln in lines[:3]), box=(0, 0, 2400, 700)),
        LayoutBlock(label="table", text=table, box=(100, 780, 2300, 1000)),
    )})
    acct = bank_statement(PageGroup(kind=PageKind.BANK_STATEMENT, pages=[page]), "statement-1").account_number
    assert acct.value is None


def test_dr_cr_headers_mark_a_transaction_table():
    from hklv_extract.extractors import _TX_WORDS

    assert _TX_WORDS.search("Dr. Amount") and _TX_WORDS.search("Cr. Amount")
    assert not _TX_WORDS.search("Account Number") and not _TX_WORDS.search("Equivalent (USD)")


def test_in_word_label_in_its_own_box_reads_the_value_on_its_row():
    page = _old_birth_page(dob="# #")
    lines = [ln for ln in page.lines if not ln.text.startswith("In Word")]
    label = TextLine(text="In Word:", score=0.99, box=(100, 2000, 330, 2040))
    value = TextLine(text="5th August, 2001", score=0.99, box=(410, 2000, 900, 2040))
    reg = TextLine(text="Date of Registration: 12/09/2001", score=0.99, box=(100, 2060, 1500, 2100))
    page = page.model_copy(update={"lines": (*lines, label, value, reg)})
    page = page.model_copy(update={"blocks": (LayoutBlock(label="text", text=page.line_text, box=(0, 0, 2400, 2200)),)})
    assert _old_birth(page).date_of_birth.value == date(2001, 8, 5)

    page = page.model_copy(update={"lines": (*lines, label, reg)})  # nothing to its right
    assert _old_birth(page).date_of_birth.value is None  # never the registration date below


# Review round 5.


@pytest.mark.parametrize(
    "body",
    [
        _line("Equivalent Balance (Exchange Rate: 124.25 as on 28 October, 2026).", 100, 1050, 1700),
        _line("Date: 29.10.2026", 100, 1150, 600),
        _line("Exchange Rate: 1 USD = BDT 122.00", 100, 1000, 1050),
    ],
)
def test_letter_text_below_the_table_does_not_make_the_column_unclear(body):
    acct = _solvency(_letter(HEADERS, [_row(900, ACCOUNT), [body]])).account_number
    assert acct.value == ACCOUNT and acct.confidence == FALLBACK_MAX


def test_another_number_in_the_column_still_makes_it_unclear():
    below = [_line("8877665544", 420, 1100, 690)]  # wholly inside the column
    acct = _solvency(_letter(HEADERS, [_row(900, ACCOUNT), below], table=None)).account_number
    assert acct.value is None


@pytest.mark.parametrize(
    "right",
    ["Date of Registration: 12/09/2001", "Date of Issue: 03/01/2015"],
)
def test_split_in_word_label_takes_only_the_nearest_cell(right):
    page = _old_birth_page(dob="# #")
    lines = [ln for ln in page.lines if not ln.text.startswith("In Word")]
    row = (
        TextLine(text="In Word:", score=0.99, box=(100, 2000, 330, 2040)),
        TextLine(text="Fifth August Two Thousand One", score=0.99, box=(410, 2000, 1100, 2040)),
        TextLine(text=right, score=0.99, box=(1500, 2000, 2300, 2040)),
    )
    page = page.model_copy(update={"lines": (*lines, *row)})
    page = page.model_copy(update={"blocks": (LayoutBlock(label="text", text=page.line_text, box=(0, 0, 2400, 2200)),)})
    assert _old_birth(page).date_of_birth.value == date(2001, 8, 5)


def test_in_word_line_stops_at_the_next_field():
    page = _old_birth_page(dob="# #")
    lines = [ln if not ln.text.startswith("In Word") else ln.model_copy(update={"text": "In Word: Fifth August Two Thousand One  Date of Registration: 12/09/2001"}) for ln in page.lines]
    page = page.model_copy(update={"lines": tuple(lines)})
    page = page.model_copy(update={"blocks": (LayoutBlock(label="text", text=page.line_text, box=(0, 0, 2400, 2200)),)})
    assert _old_birth(page).date_of_birth.value == date(2001, 8, 5)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Twenty-Fifth August Two Thousand One", date(2001, 8, 25)),
        ("Thirty-First August Two Thousand One", date(2001, 8, 31)),
        ("TWENTY-FIRST MAY NINETEEN NINETY EIGHT", date(1998, 5, 21)),
        ("Twenty - Second May Two Thousand", date(2000, 5, 22)),
        ("Twenty Fifth August Two Thousand One", date(2001, 8, 25)),
    ],
)
def test_hyphenated_ordinal_days(text, expected):
    from hklv_extract.dates import parse_words_date

    assert parse_words_date(text) == expected


# Review round 6: one reader's column alone is never confident.


@pytest.mark.parametrize(
    "second",
    [
        _line("2 0987654321098", 200, 980, 690),  # joined with its serial cell
        _line("0987654321098 01-05-2025", 420, 980, 1000),  # joined with its date cell
        _line("0987-6543210-98-0001", 420, 980, 870),  # wider than the header band
    ],
)
def test_second_account_joined_with_a_neighbour_is_still_seen(second):
    acct = _solvency(_letter(HEADERS, [_row(900, ACCOUNT), [second]], table=None)).account_number
    assert not acct.is_reliable(0.9)


def test_wrapped_tail_joined_with_the_next_column_is_still_seen():
    row = [_line("1", 200, 900, 230), _line("2050123456789", 420, 900, 690), _line("0123 2026", 420, 945, 900)]
    acct = _solvency(_letter(HEADERS, [row], table=None)).account_number
    assert not acct.is_reliable(0.9)


def test_one_readers_column_alone_is_not_confident():
    acct = _solvency(_letter(HEADERS, [_row(900, ACCOUNT)], table=None)).account_number
    assert acct.value == ACCOUNT and not acct.is_reliable(0.9)  # no VL table: FLAG


@pytest.mark.parametrize("right", ["Date of Issuance: 03/01/2015", "Date of Registration: 12/09/2001", "03/01/2015"])
def test_in_word_never_takes_another_fields_box_or_a_numeric_date(right):
    page = _old_birth_page(dob="# #")
    lines = [ln for ln in page.lines if not ln.text.startswith("In Word")]
    row = (TextLine(text="In Word:", score=0.99, box=(100, 2000, 330, 2040)), TextLine(text=right, score=0.99, box=(410, 2000, 1100, 2040)))
    page = page.model_copy(update={"lines": (*lines, *row)})
    page = page.model_copy(update={"blocks": (LayoutBlock(label="text", text=page.line_text, box=(0, 0, 2400, 2200)),)})
    assert _old_birth(page).date_of_birth.value is None


# Review round 7.


@pytest.mark.xfail(strict=True, reason="Known, unchanged from before: the labelled lookup takes a serial "
                   "number joined to the account number on the line after the label.")
def test_serial_joined_by_both_readers_in_a_narrow_column_is_not_confident():
    headers = [_line("Sl. No.", 220, 800, 330), _line("Account Number", 400, 800, 700)]
    table = LETTER_TABLE.replace(f"<tr><td>1</td><td>{ACCOUNT}</td>", f"<tr><td></td><td>1 {ACCOUNT}</td>")
    row = [_line("1 " + ACCOUNT, 270, 900, 690)]
    acct = _solvency(_letter(headers, [row], table=table)).account_number
    assert not acct.is_reliable(0.9)


@pytest.mark.parametrize(
    "in_word",
    [
        ["In Word: Twenty Eighth September Two Thousand", "Six"],  # wrapped: reads as 2000
        ["In Word: Eighth May, Two Thousand Six Date of Registration 12/05/2015"],
        ["In Word: 8th May, 2006"],
    ],
)
def test_in_word_date_is_never_confident_on_its_own(in_word):
    page = _old_birth_page(dob="# #")
    lines = [ln for ln in page.lines if not ln.text.startswith("In Word")]
    extra = tuple(TextLine(text=t, score=0.99, box=(100, 2000 + 60 * i, 1500, 2040 + 60 * i)) for i, t in enumerate(in_word))
    page = page.model_copy(update={"lines": (*lines, *extra)})
    page = page.model_copy(update={"blocks": (LayoutBlock(label="text", text=page.line_text, box=(0, 0, 2400, 2400)),)})
    assert not _old_birth(page).date_of_birth.is_reliable(0.9)


def test_boxed_date_of_birth_is_read_as_evidence():
    dob = _old_birth(_old_birth_page()).date_of_birth
    assert dob.value == date(2001, 8, 5) and dob.confidence == FALLBACK_MAX


# Review round 8.


@pytest.mark.parametrize(
    "row,expect_reliable_wrong",
    [
        # VL keeps the serial in its own cell, so the joined value already scores DISAGREE.
        ([_line("1 " + ACCOUNT, 200, 900, 690), _line("05-10-2026", 790, 900, 1020)], "05-10-2026"),
        ([_line("1", 200, 900, 230), _line("05-10-2026", 790, 900, 1020)], "05-10-2026"),  # PP missed the number
    ],
)
def test_header_row_label_never_takes_another_cell_on_the_next_line(row, expect_reliable_wrong):
    table = LETTER_TABLE.replace("05 October, 2026", "05-10-2026")
    acct = _solvency(_letter(MERGED_HEADER, [row], table=table)).account_number
    assert not (acct.value == expect_reliable_wrong and acct.is_reliable(0.9))
    assert not acct.is_reliable(0.9) or acct.value == ACCOUNT


@pytest.mark.xfail(
    reason="Known, unchanged from before: the labelled lookup's next-line fallback after a "
    "header row read as one line takes the first number-shaped cell (here a Customer ID).",
    strict=True,
)
def test_customer_id_column_left_of_account_number_is_not_taken():
    merged = [_line("Sl. No. Customer ID Account Number Account Type", 150, 800, 1400)]
    table = (
        "<table><tr><td>Sl. No.</td><td>Customer ID</td><td>Account Number</td><td>Account Type</td></tr>"
        f"<tr><td>1</td><td>88776655</td><td>{ACCOUNT}</td><td>Savings</td></tr></table>"
    )
    row = [_line("1", 200, 900, 230), _line("88776655", 400, 900, 600), _line(ACCOUNT, 700, 900, 1000), _line("Savings", 1100, 900, 1300)]
    acct = _solvency(_letter(merged, [row], table=table)).account_number
    assert acct.value != "88776655"


def test_real_layout_with_the_serial_column_right_beside_account_number_is_read():
    headers = [
        _line("Account", 400, 740, 900), _line("Balance", 1500, 740, 2000),
        _line("Sl. No.", 160, 770, 270),
        _line("Account Number", 330, 800, 680), _line("Open Date", 780, 800, 960),
        _line("Account Type", 1050, 800, 1350), _line("(BDT)", 1500, 800, 1650), _line("Equivalent (USD)", 1800, 800, 2100),
    ]
    row = [_line("1", 203, 898, 227), _line(ACCOUNT, 360, 900, 650), _line("05 October, 2026", 780, 900, 1000),
           _line("Savings Bank Account", 1050, 900, 1400), _line("12,34,500.00", 1500, 900, 1700)]
    below = [_line("Equivalent Balance (Exchange Rate: 124.25 as on 28 October, 2026).", 100, 1100, 1700)]
    acct = _solvency(_letter(headers, [row, below])).account_number
    assert acct.value == ACCOUNT and acct.confidence == FALLBACK_MAX


def test_labelled_account_number_forms_still_work():
    for lines, want in [
        (["SAMPLE BANK PLC", "SOLVENCY CERTIFICATE", "A/C No: 5555 6666 7777"], "555566667777"),
        (["SAMPLE BANK PLC", "SOLVENCY CERTIFICATE", "Account Number", "5555 6666 7777"], "555566667777"),
    ]:
        assert _solvency(make_page(lines)).account_number.value == want


def test_parents_br_number_is_never_the_childs():
    page = _old_birth_page(brn="2 0 0 O 0 2 1 5 1 2 3 4 5 6 7 8 9")  # one box read as the letter O
    lines = [ln if not ln.text.startswith("Father's BRN") else ln.model_copy(update={"text": "Father's BR No.: 19701234567890123"}) for ln in page.lines]
    page = page.model_copy(update={"lines": tuple(lines)})
    page = page.model_copy(update={"blocks": (LayoutBlock(label="text", text=page.line_text, box=(0, 0, 2400, 2400)),)})
    brn = _old_birth(page).registration_number
    assert brn.value != "19701234567890123"


# Review round 9: the labelled lookup is HEAD's own again; these layouts must read as before.


@pytest.mark.parametrize(
    "lines",
    [
        [_line("Account No", 100, 360, 380), _line("1501234567001", 700, 360, 1100),
         _line("Fund Transfer to A/C No: 2059876543210", 100, 900, 1600)],
        [_line("Account Number", 100, 360, 420), _line(":", 450, 360, 470), _line("1501234567001", 700, 360, 1100)],
        [_line("This is to certify that Md Kamal Uddin has been maintaining a Savings Account No.", 100, 360, 2300),
         _line("1501234567001 with our branch since 05/10/2016.", 100, 420, 1800)],
        [_line("Account Number", 100, 360, 420), _line("1501234567001", 100, 420, 600),
         _line("Please quote your Account No. in all correspondence.", 100, 3000, 1800)],
    ],
)
def test_common_labelled_layouts_read_as_before(lines):
    from hklv_extract.extractors import bank_statement
    from hklv_extract.group import PageGroup

    page = make_page([]).model_copy(update={"lines": (_line("SAMPLE BANK PLC", 100, 100, 800), *lines)})
    page = page.model_copy(update={"blocks": (LayoutBlock(label="text", text="Account No. : 1501234567001\n" + page.line_text, box=(0, 0, 2400, 3100)),)})
    acct = bank_statement(PageGroup(kind=PageKind.BANK_STATEMENT, pages=[page]), "statement-1").account_number
    assert acct.value == "1501234567001" and acct.is_reliable(0.9)


def test_a_date_is_never_an_account_number():
    page = make_page(["SAMPLE BANK PLC", "SOLVENCY CERTIFICATE", "Account Number", "05-10-2026"])
    assert _solvency(page).account_number.value != "05-10-2026"


# Review round 10: nothing worse than before these changes.


@pytest.mark.parametrize("line", ["A/C No: 01 1234567 01", "Account Number : 15 01234567001", "A/C No: 0 1 2 3 4 5 6 7 8 9 0 1 2"])
def test_labelled_account_numbers_with_short_groups_read_as_before(line):
    acct = _solvency(make_page(["SAMPLE BANK PLC", "SOLVENCY CERTIFICATE", line])).account_number
    assert acct.is_reliable(0.9)


def test_an_eight_digit_id_under_a_date_header_is_not_the_letter_date():
    lines = [_line("SAMPLE BANK PLC", 100, 100, 800), _line("29 October 2026", 1800, 200, 2300),
             _line("Customer ID", 100, 800, 400), _line("Account No", 500, 800, 800), _line("Opening Date", 900, 800, 1200),
             _line("20110523", 100, 900, 400), _line(ACCOUNT, 500, 900, 800), _line("05-10-2015", 900, 900, 1200)]
    page = make_page([]).model_copy(update={"lines": tuple(lines)})
    page = page.model_copy(update={"blocks": (LayoutBlock(label="text", text=page.line_text, box=(0, 0, 2400, 1000)),)})
    assert _solvency(page).letter_date.value != date(2011, 5, 23)


def test_br_number_does_not_take_a_following_box_digit():
    cert = _old_birth(_old_birth_page(brn="1999 02 15 1234 5678 9 1"))
    assert cert.registration_number.value != "199902151234567891"
    assert not (cert.registration_number.value or "").startswith("19990215123456789") or len(cert.registration_number.value) == 17


def test_checklist_table_naming_the_certificate_is_not_one():
    page = make_page(["Document Checklist", "01", "Passport", "02", "Birth Registration Certificate",
                      "03", "Parents' NID / BRN", "issued by the Registrar of Birth and Death"])
    assert classify_page(page, TODAY).kind != PageKind.BIRTH_CERTIFICATE


def test_old_style_certificate_with_a_garbled_title_still_needs_a_real_brn():
    page = _old_birth_page(title="Birfh Regiftration Certifcate")
    assert classify_page(page, TODAY).kind == PageKind.BIRTH_CERTIFICATE


# Review round 11.


FDR_HEADERS = [_line("Sl. No.", 150, 800, 300), _line("Account Number", 400, 800, 700), _line("Type", 800, 800, 950),
               _line("Opening Date", 1000, 800, 1250), _line("Amount (BDT)", 1300, 800, 1550)]
FDR_TABLE = ("<table><tr><td>Sl. No.</td><td>Account Number</td><td>Type</td><td>Opening Date</td><td>Amount (BDT)</td></tr>"
             "<tr><td>1</td><td>2059876543210</td><td>FDR</td><td>05-10-2025</td><td>5,00,000.00</td></tr></table>")
FDR_ROW = [_line("1", 200, 900, 230), _line("2059876543210", 420, 900, 690), _line("FDR", 800, 900, 900)]


@pytest.mark.parametrize(
    "holder",
    [
        "Savings Account No: 1501XXXXX7001 with us and also holds:",
        "Savings Account No: 1501****7001 with us and also holds:",
        "Md Kamal Uddin is maintaining Savings A/C # 1501234567001 with our branch.",
    ],
)
def test_a_deposit_table_beside_the_holders_own_account_is_not_confident(holder):
    acct = _solvency(_letter(FDR_HEADERS, [FDR_ROW, [_line(holder, 100, 600, 2300)]], table=FDR_TABLE)).account_number
    assert not (acct.value == "2059876543210" and acct.is_reliable(0.9))


def test_boxed_date_of_birth_never_comes_from_the_registration_date_below():
    page = _old_birth_page(dob="0 5 0 8")  # the boxes did not read
    lines = list(page.lines) + [TextLine(text="Date of Registration:", score=0.99, box=(100, 575, 600, 615)),
                                TextLine(text="12 09 2010", score=0.99, box=(700, 575, 1000, 615))]
    lines = [ln for ln in lines if not ln.text.startswith("In Word")]
    page = page.model_copy(update={"lines": tuple(lines)})
    page = page.model_copy(update={"blocks": (LayoutBlock(label="text", text=page.line_text, box=(0, 0, 2400, 3100)),)})
    assert _old_birth(page).date_of_birth.value != date(2010, 9, 12)


@pytest.mark.parametrize(
    "father_line",
    ["Father\u2019s BR No: 19701234567890123", "Father's Name: MD ABDUL KARIM  BR No: 19701234567890123"],
)
def test_parents_br_number_is_never_the_childs_whatever_the_apostrophe(father_line):
    page = _old_birth_page(brn="2 0 0 # 0 2 1 5 1 2 3 4 5 6 7 8 9")
    lines = [ln.model_copy(update={"text": father_line}) if ln.text.startswith("Father's BRN") else ln for ln in page.lines]
    page = page.model_copy(update={"lines": tuple(lines)})
    page = page.model_copy(update={"blocks": (LayoutBlock(label="text", text=page.line_text, box=(0, 0, 2400, 2400)),)})
    assert _old_birth(page).registration_number.value != "19701234567890123"


# Review round 12: a value only the fallback lookups found is never confident, and the
# label's row is cut at the next field.

from hklv_extract.extractors import FALLBACK_MAX  # noqa: E402


@pytest.mark.parametrize(
    "holder",
    ["Md Kamal Uddin is maintaining Savings Acct. No. 1501234567001 with our branch.",
     "SND No. 1501234567001", "Savings A/C No. 117.101.0012345"],
)
def test_a_deposit_table_is_never_confident_whatever_the_holder_label(holder):
    acct = _solvency(_letter(FDR_HEADERS, [FDR_ROW, [_line(holder, 100, 600, 2300)]], table=FDR_TABLE)).account_number
    assert not acct.is_reliable(0.9)


@pytest.mark.parametrize("number", ["01-12-2024-0001234", "2050-10-12-0012345", "0101-01-01-0012345"])
def test_dashed_account_numbers_with_a_date_shaped_group_read_as_before(number):
    acct = _solvency(make_page(["SAMPLE BANK PLC", "SOLVENCY CERTIFICATE", f"A/C No: {number}"])).account_number
    assert acct.value == number and acct.is_reliable(0.9)


def test_br_number_fallback_never_reads_the_line_below():
    page = _old_birth_page(brn="2OO1 0215 1234 5678 9")
    lines = [ln for ln in page.lines if not ln.text.startswith("Father's BRN")]
    extra = (TextLine(text="Father's BR No:", score=0.99, box=(100, 395, 500, 435)),
             TextLine(text="19701234567890123", score=0.99, box=(100, 440, 600, 480)))
    page = page.model_copy(update={"lines": (*lines, *extra)})
    page = page.model_copy(update={"blocks": (LayoutBlock(label="text", text=page.line_text, box=(0, 0, 2400, 2400)),)})
    assert _old_birth(page).registration_number.value != "19701234567890123"


def test_boxed_date_of_birth_stops_at_the_next_field_on_its_row():
    page = _old_birth_page(dob="# #")
    lines = [ln for ln in page.lines if not ln.text.startswith(("Date of Birth", "In Word"))]
    row = (TextLine(text="Date of Birth:", score=0.99, box=(100, 520, 500, 560)),
           TextLine(text="Date of Registration:", score=0.99, box=(1300, 520, 1800, 560)),
           TextLine(text="12 09 2010", score=0.99, box=(1850, 520, 2200, 560)))
    page = page.model_copy(update={"lines": (*lines, *row)})
    page = page.model_copy(update={"blocks": (LayoutBlock(label="text", text=page.line_text, box=(0, 0, 2400, 2400)),)})
    assert _old_birth(page).date_of_birth.value != date(2010, 9, 12)


# Review round 13.


def test_citizenship_certificate_with_nid_brn_and_a_registrar_signature_is_not_a_birth_certificate():
    page = make_page(["No. 5 Sample Union Parishad", "CITIZENSHIP CERTIFICATE",
                      "This is to certify that ABDUL KARIM, Father: ABDUL MALEK, is a citizen of Bangladesh.",
                      "Date of Birth: 01/01/1970, NID/BRN: 19701234567890123",
                      "Chairman and Registrar of Birth and Death"])
    assert classify_page(page, TODAY).kind != PageKind.BIRTH_CERTIFICATE


def test_cover_letter_with_the_applicants_brn_is_not_a_birth_certificate():
    page = make_page(["To", "The Visa Officer", "Applicant: KAMAL UDDIN", "Date of Birth: 05/08/2001",
                      "BRN: 20010215123456789", "Enclosures:", "Birth Registration Certificate",
                      "issued by the Registrar of Birth and Death"])
    assert classify_page(page, TODAY).kind != PageKind.BIRTH_CERTIFICATE


def test_old_style_certificate_never_merges_with_the_next_birth_certificate():
    parent = make_page(["Office of the Birth and Death Registrar", "BDR Form-3", "Register No. 3",
                        "BR Number: 19751234567890123", "Name: ABDUL KARIM", "Date of Birth: 01/01/1975",
                        "Date of Registration: 02/02/1975"], page_no=1)
    student = make_page(["Birth Registration Number: 20061234567890123", "Name: RAHIM UDDIN",
                         "Date of Birth: 08/05/2006", "Father's Name: ABDUL KARIM"], page_no=2)
    groups = groups_for(parent, student)
    assert [g.kind for g in groups] == [PageKind.BIRTH_CERTIFICATE, PageKind.BIRTH_CERTIFICATE]
    assert [g.page_nos for g in groups] == [(1,), (2,)]


# Review round 14.


@pytest.mark.parametrize("field", ["BRN/NID", "BR No/NID", "NID or BRN", "NID No. (BRN)", "BRN / NID No", "NID/BRN"])
def test_citizenship_certificate_with_any_combined_identity_field_is_not_a_birth_certificate(field):
    page = make_page(["No. 5 Sample Union Parishad", "CITIZENSHIP CERTIFICATE",
                      "This is to certify that ABDUL KARIM, Father: ABDUL MALEK, is a citizen of Bangladesh.",
                      f"Date of Birth: 01/01/1970, {field}: 19701234567890123", "Place of Birth: Sample Village",
                      "Chairman and Registrar of Birth and Death"])
    assert classify_page(page, TODAY).kind != PageKind.BIRTH_CERTIFICATE


def test_cover_letter_with_place_of_birth_and_brn_is_not_a_birth_certificate():
    page = make_page(["To", "The Visa Officer", "Applicant: KAMAL UDDIN", "Date of Birth: 15/02/1999",
                      "Place of Birth: Dhaka", "BRN: 19990215123456789", "Enclosures:",
                      "2. Birth Registration Certificate issued by the Registrar of Birth and Death"])
    assert classify_page(page, TODAY).kind != PageKind.BIRTH_CERTIFICATE


# Review round 15.


def test_birth_registration_application_form_is_not_a_birth_certificate():
    page = make_page(["Application Form for Birth Registration (Late Registration)",
                      "To, The Registrar of Birth and Death, Sample Union Parishad",
                      "Name of Child: KAMAL UDDIN", "Date of Birth: 05/08/2001", "Order of Child: 2",
                      "Father's BRN: 19701234567890123", "For office use only",
                      "Register No.:", "Date of Registration:"])
    assert classify_page(page, TODAY).kind != PageKind.BIRTH_CERTIFICATE


@pytest.mark.parametrize("title", ["CITIZENSHIP CERTIFICATE", "CHARACTER CERTIFICATE", "WARISH CERTIFICATE"])
def test_union_parishad_certificates_with_a_register_serial_are_not_birth_certificates(title):
    page = make_page(["Sample Union Parishad", title, "Register No. 12",
                      "This is to certify that KAMAL UDDIN, Date of Birth 05/08/2001, BRN 20012690123456789",
                      "Chairman, Sample Union Parishad & Registrar of Birth and Death"])
    assert classify_page(page, TODAY).kind != PageKind.BIRTH_CERTIFICATE


def test_old_style_original_joins_its_own_translation():
    original = make_page(["Office of the Birth and Death Registrar", "Register No. 12",
                          "BR Number: 2 0 0 1 0 2 1 5 1 2 3 4 5 6 7 8 9", "Name: KAMAL UDDIN",
                          "Date of Birth: 05 08 2001", "Date of Registration: 11/04/2002"], page_no=1)
    translation = make_page(["English Translation", "Birth Registration Number: 20010215123456789",
                             "Name: KAMAL UDDIN", "Date of Birth: 05/08/2001"], page_no=2)
    groups = groups_for(original, translation)
    assert [g.page_nos for g in groups] == [(1, 2)]


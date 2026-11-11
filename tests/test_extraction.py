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

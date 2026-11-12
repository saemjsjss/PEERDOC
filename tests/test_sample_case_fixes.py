"""Misreads found on a highlighted real case (2026-11-13). Boxes copied from it (300 dpi);
names and numbers fictional or from the MRZ check-digit example."""

from datetime import date

from hklv_extract.classify import PageKind, classify_page
from hklv_extract.extractors import academic_certificate, academic_transcript, bank_solvency, tin_certificate, trade_license
from hklv_extract.group import PageGroup, page_identity
from hklv_ocr.reading import LayoutBlock, PageReading, TextLine

TODAY = date(2026, 6, 30)


def page(*lines, vl=None):
    tl = tuple(TextLine(text=t, score=s, box=b) for t, s, b in lines)
    text = "\n".join(t for t, _, _ in lines) if vl is None else vl
    return PageReading(
        page_no=1, source_file="f.pdf", file_page=1, from_image_file=False, width=2480, height=3508,
        lines=tl, blocks=(LayoutBlock(label="text", text=text, box=(0, 0, 2480, 3508)),),
    )


def group(kind, p):
    return PageGroup(kind=kind, pages=[p], classes=[classify_page(p, TODAY)])


def test_mrz_line_split_into_pieces_is_joined_and_the_doubled_letter_dropped():
    p = page(
        ("PASSPORT", 1.0, (555, 1870, 766, 1921)),
        ("AHAMED", 1.0, (885, 2013, 1146, 2072)),
        ("P<BGD", 0.99, (466, 2707, 634, 2754)),
        ("DAHAMED<<MD<RIFAT", 1.0, (615, 2706, 1224, 2771)),  # overlaps 'P<BGD': its D read twice
        ("<<<<<<<<<<<<<<<<<<<<<<", 0.98, (1258, 2710, 2044, 2754)),
        ("A216301740BGD0510017M36020149596637349<<<<54", 1.0, (467, 2791, 2045, 2845)),
    )
    c = classify_page(p, TODAY)
    assert c.kind == PageKind.PASSPORT
    assert c.mrz.valid and c.mrz.surname == "AHAMED" and c.mrz.given_names == "MD RIFAT"


def test_full_width_colon_before_an_nid_number_is_stripped():
    p = page(
        ("NATIONAL ID CARD", 1.0, (970, 757, 1648, 837)),
        ("ID No.", 1.0, (895, 1317, 1077, 1385)),
        ("：9596637349", 0.96, (1265, 1334, 1716, 1396)),
    )
    assert page_identity(p, classify_page(p, TODAY)) == "9596637349"


def test_misspelt_trade_licence_translation_with_owner_and_years():
    p = page(
        ("Translated True Copy", 0.99, (994, 455, 1511, 519)),
        ("TREADE LICENSE", 1.0, (900, 600, 1500, 660)),
        ("Issue Date: 10/03/2026", 1.0, (1681, 1064, 2240, 1154)),
        ("Name of Owner/Director's: ABUL KHAYER", 0.99, (271, 1220, 1378, 1290)),
        ("specified business within this union for the years 2025 to 2026 permission was granted to", 1.0, (249, 1866, 2229, 1971)),
    )
    assert classify_page(p, TODAY).kind == PageKind.TRADE_LICENSE
    t = trade_license(group(PageKind.TRADE_LICENSE, p), "t")
    assert t.owner_name.value == "ABUL KHAYER"
    assert t.fiscal_year.value == "2025-2026"
    assert t.issue_date.value == date(2026, 3, 10)


def test_solvency_holder_after_certify_that_comma_and_number_column():
    p = page(
        ("This is to certify that, ABUL KHAYER,", 0.99, (257, 1064, 1057, 1134)),
        ("father ofMD RIFAT AHAMED,", 1.0, (1073, 1063, 1724, 1127)),
        ("account with our Bank satisfactorily. To the best of our knowledge the account holder is financially", 0.99, (261, 1210, 2225, 1267)),
        ("Type of", 1.0, (445, 1394, 610, 1463)),
        ("Number", 1.0, (1093, 1431, 1261, 1485)),
        ("513431500000560", 1.0, (993, 1527, 1338, 1579)),
    )
    table = LayoutBlock(
        label="table",
        text="<table><tr><td>SL</td><td>Type of Account</td><td>Number</td></tr>"
        "<tr><td>01</td><td>Saving Bank Account</td><td>513431500000560</td></tr></table>",
        box=(250, 1390, 2250, 1700),
    )
    p = p.model_copy(update={"blocks": (*p.blocks, table)})
    s = bank_solvency(group(PageKind.BANK_SOLVENCY, p), "s")
    assert s.account_holder.value == "ABUL KHAYER"
    assert s.account_number.value == "513431500000560"
    assert not s.account_number.is_reliable(0.9)  # one column reading: BANK-02's exact-match rule decides


def test_tin_name_from_its_sentence_when_the_label_is_smudged():
    p = page(
        ("Taxpayer's Identification Number (TIN) Certificate", 1.0, (500, 900, 1900, 960)),
        ("This is to Certify that ABUL KHAYER is a Registered Taxpayer of National Board of Revenue under the", 1.0, (189, 1247, 2186, 1305)),
        ("e : ABUL KHAYER", 0.98, (333, 1491, 764, 1560)),
    )
    t = tin_certificate(group(PageKind.TIN_CERTIFICATE, p), "tin")
    assert t.taxpayer_name.value == "ABUL KHAYER"
    assert t.taxpayer_name.is_reliable(0.9)


def test_stamp_word_over_the_date_of_birth_sentence_is_left_out():
    p = page(
        ("SECONDARY SCHOOL CERTIFICATE EXAMINATION", 1.0, (900, 700, 2700, 780)),
        ("His/Her date of birth as recorded in his / her registration card is First October Two", 0.99, (617, 1711, 2935, 1812)),
        ("otarized", 1.0, (1928, 1774, 2176, 1837)),
        ("Thousand Five.", 1.0, (623, 1808, 1041, 1879)),
    )
    assert academic_certificate(group(PageKind.ACADEMIC_CERTIFICATE, p), "c").date_of_birth.value == date(2005, 10, 1)


def test_narme_of_student_label():
    p = page(
        ("ACADEMIC TRANSCRIPT", 1.0, (700, 800, 1500, 860)),
        ("Narme of Student", 0.97, (327, 930, 691, 980)),
        ("Md. Rifat Ahamed", 1.0, (785, 934, 1202, 996)),
    )
    assert academic_transcript(group(PageKind.ACADEMIC_TRANSCRIPT, p), "t").student_name.value == "Md. Rifat Ahamed"

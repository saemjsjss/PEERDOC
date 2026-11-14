"""RULES-v5 extraction: notary/translator stamp dates and the solvency's USD/BDT amounts.
Layouts copied from a real case (boxes in pixels at 300 dpi); names and numbers fictional."""

from datetime import date

from hklv_extract.classify import PageKind
from hklv_extract.common_fields import stamp_dates
from hklv_extract.extractors import bank_solvency
from hklv_extract.group import PageGroup
from hklv_ocr.reading import LayoutBlock, PageReading, TextLine


def page(*lines, vl=None):
    tl = tuple(TextLine(text=t, score=s, box=b) for t, s, b in lines)
    text = "\n".join(t for t, _, _ in lines) if vl is None else vl
    return PageReading(
        page_no=1, source_file="f.pdf", file_page=1, from_image_file=False, width=2480, height=3508,
        lines=tl, blocks=(LayoutBlock(label="text", text=text, box=(0, 0, 2480, 3508)),),
    )


def test_notary_and_translator_dates_on_a_translation_page():
    p = page(
        (": 01 Oct 2005", 0.95, (1282, 1223, 1660, 1290)),  # the card's own date of birth
        ("Notarized", 1.0, (1763, 2654, 2045, 2722)),
        ("TRANSLATED BY", 0.98, (367, 2688, 846, 2803)),
        ("10-06-2026", 0.96, (593, 2741, 918, 2861)),
        ("Notary Public (Whole of Bangladesh)", 1.0, (1678, 2847, 2153, 2881)),
        ("0 9 JUN 2026", 0.98, (1799, 3007, 2179, 3117)),
    )
    notary, translator = stamp_dates([p])
    assert [d.value for d in notary] == [date(2026, 6, 9)]
    assert [d.value for d in translator] == [date(2026, 6, 10)]
    assert notary[0].confidence >= 0.85


def test_split_day_digits_are_joined():
    p = page(
        ("ATTESTED BY ME", 0.97, (884, 2298, 1310, 2357)),
        ("2 9 JUN 2026", 0.99, (1095, 2338, 1462, 2440)),
    )
    assert [d.value for d in stamp_dates([p])[0]] == [date(2026, 6, 29)]


def test_document_dates_near_the_notary_are_not_stamp_dates():
    p = page(
        ("Advocate, Dhaka Judge Court", 0.99, (1600, 2400, 2100, 2450)),
        ("Date of Publication of Results : 28 July, 2023", 1.0, (900, 2500, 1900, 2550)),
        ("15 October, 2024.", 1.0, (1600, 2470, 1950, 2520)),
        ("01-01-1983", 1.0, (1650, 2700, 1850, 2735)),  # a table cell, too far for a bare date
    )
    assert stamp_dates([p]) == ((), ())


def test_a_date_in_another_column_is_ignored():
    p = page(
        ("Notary Public (Whole of Bangladesh)", 1.0, (1700, 2000, 2180, 2060)),
        ("09 JUN 2026", 0.99, (300, 2100, 700, 2200)),
    )
    assert stamp_dates([p]) == ((), ())


def solvency(*lines, vl=None):
    return bank_solvency(PageGroup(kind=PageKind.BANK_SOLVENCY, pages=[page(*lines, vl=vl)]), "s")


def test_amounts_written_with_their_currency():
    s = solvency(
        ("USD@124.50 BDT", 1.0, (1817, 1462, 2199, 1513)),
        ("BDT. 2,407,592.52", 0.99, (1472, 1521, 1760, 1578)),
        ("USD 19,338.09", 1.0, (1867, 1524, 2147, 1590)),
    )
    assert s.usd_amount.value == "USD 19,338.09"
    assert s.bdt_amount.value == "BDT. 2,407,592.52"


def test_amounts_under_currency_column_headers():
    s = solvency(
        ("Balance (BDT)", 1.0, (1378, 1525, 1656, 1579)),
        ("Balance (USD)", 1.0, (1822, 1523, 2094, 1575)),
        ("01", 1.0, (1900, 1600, 1950, 1630)),  # a row number is no amount
        ("24,99,732.50", 1.0, (1403, 1639, 1638, 1693)),
        ("20191.88(Approximately)", 0.98, (1729, 1638, 2185, 1689)),
        vl="",
    )
    assert s.usd_amount.value == "20191.88(Approximately)"
    assert s.bdt_amount.value == "24,99,732.50"


def test_exchange_rate_alone_is_no_usd_amount():
    s = solvency(
        ("The existing balance as on 15-JUN-2025 is BDT 18,01,984.00", 1.0, (230, 1300, 2190, 1360)),
        ("Exchange Rate 1 USD = 123.70", 1.0, (230, 1400, 1200, 1460)),
    )
    assert not s.usd_amount.found
    assert s.bdt_amount.value == "BDT 18,01,984.00"


def test_usd_amount_touching_its_code():
    # Islami Bank letter: no space between 'USD' and the amount
    s = solvency(
        ("the said account is BDT 1606417.50 as on 25.10.2026(USD12965.43) only. Our Routing number", 0.98, (130, 760, 1620, 800)),
    )
    assert s.usd_amount.value == "USD12965.43"
    assert s.bdt_amount.value == "BDT 1606417.50"


def test_exchange_rate_in_a_column_header_is_no_bdt_amount():
    # SBAC letter: the USD column's header gives the rate '01 USD is equivalent to BDT 123.95'
    s = solvency(
        ("Balance equivalent to USD(As", 0.99, (1180, 870, 1640, 900)),
        ("rate where 01 USD is", 0.99, (1180, 930, 1640, 960)),
        ("equivalent to BDT 123.95", 0.99, (1180, 960, 1640, 990)),
        ("Current Balance", 0.99, (910, 870, 1160, 900)),
        ("(BDT) as on", 0.99, (910, 900, 1160, 930)),
        ("4,076,500.00", 0.99, (910, 1040, 1100, 1070)),
        ("32,888.26", 0.99, (1180, 1040, 1340, 1070)),
        vl="",
    )
    assert s.bdt_amount.value == "4,076,500.00"
    assert s.usd_amount.found

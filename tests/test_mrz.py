"""MRZ parsing and check digits. All MRZ data here is fictional and generated in the test."""

from datetime import date

import pytest

from hklv_extract.mrz import check_digit, clean_line, find_mrz, parse_td1, parse_td3

TODAY = date(2026, 11, 11)


def cd(s: str) -> str:
    return str(check_digit(s))


def td3(number="K12345678", birth="990215", sex="M", expiry="310101", personal="1234567890<<<<", name="UDDIN<<KAMAL"):
    l1 = f"P<BGD{name}".ljust(44, "<")
    personal_cd = "<" if set(personal) <= {"<"} else cd(personal)
    body = f"{number}{cd(number)}BGD{birth}{cd(birth)}{sex}{expiry}{cd(expiry)}{personal}{personal_cd}"
    composite = cd(body[0:10] + body[13:20] + body[21:43])
    return [l1, body + composite]


def td1(number="5551234567", birth="700101", sex="F", expiry="360101", name="BEGUM<<RAHIMA"):
    if len(number) > 9:
        l1 = f"I<BGD{number[:9]}<{number[9:]}{cd(number)}".ljust(30, "<")
    else:
        l1 = f"I<BGD{number}{cd(number)}".ljust(30, "<")
    l2 = f"{birth}{cd(birth)}{sex}{expiry}{cd(expiry)}BGD".ljust(29, "<")
    l2 += cd(l1[5:30] + l2[0:7] + l2[8:15] + l2[18:29])
    return [l1, l2, name.ljust(30, "<")]


def test_check_digit_icao_example():
    # ICAO 9303 part 3 worked example: document number L898902C3 has check digit 6.
    assert check_digit("L898902C3") == 6
    assert check_digit("740812") == 2


def test_td3_parses_and_validates():
    r = parse_td3(td3(), TODAY)
    assert r is not None and r.valid
    assert (r.surname, r.given_names, r.full_name) == ("UDDIN", "KAMAL", "KAMAL UDDIN")
    assert r.document_number == "K12345678"
    assert r.birth_date == date(1999, 2, 15)
    assert r.expiry_date == date(2031, 1, 1)
    assert r.personal_number == "1234567890"


def test_td3_detects_a_misread_digit():
    l1, l2 = td3()
    bad = l2[:14] + ("1" if l2[14] != "1" else "2") + l2[15:]  # change one birth-date digit
    r = parse_td3([l1, bad], TODAY)
    assert r is not None and not r.valid
    assert r.checks["birth_date"] is False


def test_td1_long_number_continues_into_optional_data():
    r = parse_td1(td1(), TODAY)
    assert r is not None and r.valid
    assert r.document_number == "5551234567"
    assert (r.surname, r.given_names) == ("BEGUM", "RAHIMA")
    assert r.birth_date == date(1970, 1, 1)


def test_td1_short_number():
    r = parse_td1(td1(number="123456789"), TODAY)
    assert r is not None and r.valid and r.document_number == "123456789"


def test_ocr_noise_is_cleaned_and_digits_repaired_under_check_digit_guard():
    l1, l2, l3 = td1()
    noisy = [
        "| < B GD " + " ".join(l1[5:20]) + " < < <",  # spaced out, '|' for I, filler lost
        l2.replace("0", "O", 2),  # O for 0 in the birth date
        " ".join(l3) + ".",
    ]
    r = find_mrz(noisy, TODAY)
    assert r and r[0].valid
    assert r[0].document_number == "5551234567"


def test_extra_character_makes_line_unusable_not_guessed():
    l1, l2, l3 = td1()
    assert parse_td1([l1, l2[:10] + "7" + l2[10:], l3], TODAY) is None


def test_birth_century_uses_reference_date():
    r = parse_td3(td3(birth="300101"), TODAY)
    assert r.birth_date == date(1930, 1, 1)  # 2030 would be in the future
    r = parse_td3(td3(birth="200101"), TODAY)
    assert r.birth_date == date(2020, 1, 1)


def test_impossible_date_is_not_valid():
    l1, l2 = td3(birth="991340")
    r = parse_td3([l1, l2], TODAY)
    assert r.birth_date is None and not r.valid


def test_find_mrz_picks_valid_zone_among_page_text():
    good = td1()
    bad = [good[0], good[1][:3] + "9" + good[1][4:], good[2]]
    texts = ["NATIONAL ID CARD", "Name: RAHIMA BEGUM", *bad, "some text", *good]
    found = find_mrz(texts, TODAY)
    assert found[0].valid and not found[-1].valid


@pytest.mark.parametrize("raw,clean", [("P<BGD «UDDIN", "P<BGD<UDDIN"), ("u d d | n", "UDDIN"), ("RAH|MA<<.", "RAHIMA<<")])
def test_clean_line(raw, clean):
    assert clean_line(raw) == clean

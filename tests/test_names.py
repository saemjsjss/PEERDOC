import pytest

from hklv_rules.names import names_equal, normalize_name, same_name


@pytest.mark.parametrize(
    "a, b",
    [
        ("MD. ALI SARKER", "MOHAMMAD ALI SARKER"),
        ("Mohd Ali Sarker", "MD ALI SARKER"),
        ("MST. SHAMIMA AKTER", "MOSAMMAT SHAMIMA AKTER"),
        ("ROHAN KHAN S/O: KARIM KHAN & RINA", "ROHAN KHAN"),
        ("rina  d/o karim", "RINA"),
        ("ABU TAHER", "ABUTAHER"),
        ("MD ALI", "MOHAMMED ALI"),  # the title in any common spelling
        ("MUHAMMAD ALI", "MOHAMMAD ALI"),
        ("MST RAHIMA", "MOSAMMET RAHIMA"),
    ],
)
def test_equal_after_cleanup(a, b):
    assert names_equal(a, b)


@pytest.mark.parametrize(
    "a, b",
    [
        ("ALI ASRAF", "ALI ASHRAF"),  # spelling variant: affidavit needed
        ("RAHIMA", "RAHIMA BEGUM"),  # dropped surname: affidavit needed
        ("MST. SHAMIMA AKTER", "SHAMIMA AKTER"),  # honorific present vs absent
    ],
)
def test_not_equal(a, b):
    assert not names_equal(a, b)


def test_empty_names_never_match():
    assert normalize_name("...") == ""
    assert not names_equal("", "")


def test_same_name_ignores_word_order_only():
    assert same_name("RONY MD TANVIR AHMED", "MD TANVIR AHMED RONY")
    assert not same_name("TANVIR AHMED", "MD TANVIR AHMED RONY")


def test_title_glued_to_the_name_by_ocr_still_matches():
    assert names_equal("MSTRAHIMA KHATUN", "MST. RAHIMA KHATUN")
    assert names_equal("MDKAMALUDDINRANA", "MD KAMAL UDDIN RANA")
    assert not names_equal("MOSTAFA KAMAL", "MOSAMMAT AFA KAMAL")  # MOST- is a name, not a title

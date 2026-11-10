import pytest

from hklv_rules.names import names_equal, normalize_name


@pytest.mark.parametrize(
    "a, b",
    [
        ("MD. ALI SARKER", "MOHAMMAD ALI SARKER"),
        ("Mohd Ali Sarker", "MD ALI SARKER"),
        ("MST. SHAMIMA AKTER", "MOSAMMAT SHAMIMA AKTER"),
        ("ROHAN KHAN S/O: KARIM KHAN & RINA", "ROHAN KHAN"),
        ("rina  d/o karim", "RINA"),
        ("ABU TAHER", "ABUTAHER"),
    ],
)
def test_equal_after_cleanup(a, b):
    assert names_equal(a, b)


@pytest.mark.parametrize(
    "a, b",
    [
        ("ALI ASRAF", "ALI ASHRAF"),  # spelling variant: affidavit needed
        ("HALIMA", "HALIMA BEGUM"),  # dropped surname: affidavit needed
        ("MST. SHAMIMA AKTER", "SHAMIMA AKTER"),  # honorific present vs absent
        ("MOHAMMED ALI", "MOHAMMAD ALI"),  # spelling variants are not merged
    ],
)
def test_not_equal(a, b):
    assert not names_equal(a, b)


def test_empty_names_never_match():
    assert normalize_name("...") == ""
    assert not names_equal("", "")

"""RULES-v5 ACAD-06: SSC and HSC share the board registration number. Fictional data."""

from builders import LOW, academic_certificate, academic_transcript, context, ex
from reading_builders import make_page

from hklv_extract.classify import PageKind
from hklv_extract.extractors import academic_transcript as extract_transcript
from hklv_extract.group import PageGroup
from hklv_rules.models import AcademicLevel, Extracted, Outcome
from hklv_rules.rules.academic import check_academic

SSC, HSC = AcademicLevel.SSC, AcademicLevel.HSC


def reg(doc, number, conf=0.99):
    return doc.model_copy(update={"registration_number": ex(number, conf) if number else Extracted[str]()})


def acad06(*docs):
    return [r for r in check_academic(context(*docs)) if r.rule_id == "ACAD-06"]


def test_same_number_passes():
    [r] = acad06(reg(academic_certificate(SSC), "1910534278"), reg(academic_transcript(HSC), "1910534278"))
    assert r.outcome is Outcome.PASS
    assert "1910534278" in r.reason


def test_different_numbers_flag():
    [r] = acad06(reg(academic_certificate(SSC), "1910534278"), reg(academic_certificate(HSC), "2010617394"))
    assert r.outcome is Outcome.FLAG
    assert "1910534278" in r.reason and "2010617394" in r.reason


def test_unsure_or_missing_numbers_pass():
    [r] = acad06(reg(academic_certificate(SSC), "1910534278", LOW), reg(academic_certificate(HSC), "2010617394"))
    assert r.outcome is Outcome.PASS
    [r] = acad06(academic_certificate(SSC), academic_certificate(HSC))
    assert r.outcome is Outcome.PASS


def test_no_result_without_both_levels():
    assert acad06(reg(academic_certificate(SSC), "1910534278")) == []


def test_extracts_the_number_without_the_session():
    for line in ("Registration No.: 2013620078/2021-2022", "1310612541/2016", "Registration No. 1910627654 / 2020"):
        page = make_page(["ACADEMIC TRANSCRIPT", line])
        doc = extract_transcript(PageGroup(kind=PageKind.ACADEMIC_TRANSCRIPT, pages=[page]), "t")
        assert doc.registration_number.value == line.split("/")[0].split()[-1].lstrip(":"), line

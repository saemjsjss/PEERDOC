"""Income Tax rules (TAX-01..04). Optional documents; all data fictional."""

from decimal import Decimal

import pytest
from builders import LOW, by_rule, context, ex

from hklv_rules.models import (
    Extracted,
    IncomeTaxAcknowledgement,
    IncomeTaxCertificate,
    IncomeTaxChallan,
    OnlineCheck,
    OnlineStatus,
    Outcome,
)
from hklv_rules.rules.tax import check_income_tax

CHALLAN_NO = "2026-0101-0000123"
_DEFAULT = object()


# --- test-local builders ------------------------------------------------------------


def _money(value, confidence):
    return ex(Decimal(value), confidence) if value is not None else Extracted[Decimal]()


def challan(
    number: str | None = CHALLAN_NO,
    printed: str | None = "15000",
    online=_DEFAULT,
    number_confidence: float = 0.99,
    amount_confidence: float = 0.99,
    doc_id: str = "challan",
) -> IncomeTaxChallan:
    """Default: verified online and the website amount equals the printed amount."""
    if online is _DEFAULT:
        online = OnlineCheck(status=OnlineStatus.VERIFIED, amount=Decimal("15000"))
    return IncomeTaxChallan(
        doc_id=doc_id,
        challan_number=ex(number, number_confidence) if number is not None else Extracted[str](),
        printed_amount=_money(printed, amount_confidence),
        online=online,
    )


def acknowledgement(
    tax_paid: str | None = "25000",
    income: str | None = "6500000",
    confidence: float = 0.99,
    doc_id: str = "ack",
) -> IncomeTaxAcknowledgement:
    return IncomeTaxAcknowledgement(
        doc_id=doc_id,
        total_tax_paid=_money(tax_paid, confidence),
        total_income=_money(income, confidence),
    )


def certificate(doc_id: str = "tax-cert") -> IncomeTaxCertificate:
    return IncomeTaxCertificate(doc_id=doc_id, taxpayer_name=ex("MD. KAMAL UDDIN"))


def run(*docs):
    return by_rule(check_income_tax(context(*docs)))


# --- TAX-01 Presence ----------------------------------------------------------------


def test_no_tax_documents_passes_tax_01_only():
    results = check_income_tax(context())
    assert len(results) == 1
    [r] = results
    assert r.rule_id == "TAX-01"
    assert r.outcome is Outcome.PASS
    assert r.reason == "No Income Tax documents submitted (optional)"


def test_all_documents_valid_pass_every_rule():
    rs = run(challan(), acknowledgement(), certificate())
    assert set(rs) == {"TAX-01", "TAX-02", "TAX-03", "TAX-04"}
    assert {r.outcome for r in rs.values()} == {Outcome.PASS}
    reason = rs["TAX-01"].reason
    assert "Challan challan" in reason and "Acknowledgement ack" in reason and "Certificate tax-cert" in reason


def test_certificate_only_passes_presence_and_nothing_else():
    rs = run(certificate())
    assert set(rs) == {"TAX-01"}
    assert rs["TAX-01"].outcome is Outcome.PASS
    assert "Certificate tax-cert" in rs["TAX-01"].reason
    assert "Challan" not in rs["TAX-01"].reason


def test_no_acknowledgement_means_no_tax_02_or_03():
    assert set(run(challan())) == {"TAX-01", "TAX-04"}


def test_no_challan_means_no_tax_04():
    assert set(run(acknowledgement())) == {"TAX-01", "TAX-02", "TAX-03"}


def test_one_tax_01_and_per_document_results_for_multiple_documents():
    results = check_income_tax(
        context(acknowledgement(doc_id="ack-1"), acknowledgement(doc_id="ack-2"), challan(doc_id="c1"))
    )
    ids = [r.rule_id for r in results]
    assert ids.count("TAX-01") == 1
    assert ids.count("TAX-02") == 2 and ids.count("TAX-03") == 2 and ids.count("TAX-04") == 1


# --- TAX-02 Tax limit ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("tax_paid", "outcome"),
    [("10000", Outcome.PASS), ("10000.00", Outcome.PASS), ("9999.99", Outcome.FLAG), ("0", Outcome.FLAG)],
)
def test_tax_02_boundary(tax_paid, outcome):
    r = run(acknowledgement(tax_paid=tax_paid))["TAX-02"]
    assert r.outcome is outcome
    assert "ack" in r.reason
    assert r.evidence[0].field == "total_tax_paid"
    assert r.evidence[0].value == tax_paid


def test_tax_02_below_limit_reason():
    r = run(acknowledgement(tax_paid="8000"))["TAX-02"]
    assert r.reason == "Income Tax Acknowledgement ack: total tax paid 8,000 BDT is below 10,000 BDT"


def test_tax_02_missing_flags():
    r = run(acknowledgement(tax_paid=None))["TAX-02"]
    assert r.outcome is Outcome.FLAG
    assert "not found" in r.reason


def test_tax_02_low_confidence_flags_even_when_above_limit():
    r = run(acknowledgement(tax_paid="90000", confidence=LOW))["TAX-02"]
    assert r.outcome is Outcome.FLAG
    assert "low OCR confidence" in r.reason


# --- TAX-03 Wealth limit -----------------------------------------------------------


@pytest.mark.parametrize(
    ("income", "outcome"),
    [("5000000", Outcome.PASS), ("12000000", Outcome.PASS), ("4999999", Outcome.FLAG)],
)
def test_tax_03_boundary(income, outcome):
    r = run(acknowledgement(income=income))["TAX-03"]
    assert r.outcome is outcome
    assert r.evidence[0].field == "total_income"


def test_tax_03_pass_reason_names_document_and_amount():
    r = run(acknowledgement(income="6500000"))["TAX-03"]
    assert r.reason == "Income Tax Acknowledgement ack: total income shown 6,500,000 BDT, at least 5,000,000 BDT"


def test_tax_03_missing_flags():
    r = run(acknowledgement(income=None))["TAX-03"]
    assert r.outcome is Outcome.FLAG
    assert "not found" in r.reason


def test_tax_03_low_confidence_flags():
    r = run(acknowledgement(income="9000000", confidence=LOW))["TAX-03"]
    assert r.outcome is Outcome.FLAG
    assert "low OCR confidence" in r.reason


# --- TAX-04 Challan verification ----------------------------------------------------


def test_tax_04_verified_matching_amount_passes_with_evidence():
    r = run(challan())["TAX-04"]
    assert r.outcome is Outcome.PASS
    assert "challan" in r.reason and "15,000 BDT" in r.reason
    fields = {e.field: e.value for e in r.evidence}
    assert fields == {"challan_number": CHALLAN_NO, "printed_amount": "15000", "online.amount": "15000"}


def test_tax_04_equal_amounts_with_different_scale_pass():
    online = OnlineCheck(status=OnlineStatus.VERIFIED, amount=Decimal("15000.00"))
    assert run(challan(online=online))["TAX-04"].outcome is Outcome.PASS


def test_tax_04_amount_mismatch_fails():
    online = OnlineCheck(status=OnlineStatus.VERIFIED, amount=Decimal("1500"))
    r = run(challan(online=online))["TAX-04"]
    assert r.outcome is Outcome.FAIL
    assert "1,500 BDT does not match printed amount 15,000 BDT" in r.reason


def test_tax_04_not_found_online_fails():
    r = run(challan(online=OnlineCheck(status=OnlineStatus.NOT_FOUND)))["TAX-04"]
    assert r.outcome is Outcome.FAIL
    assert "the challan site has no such challan" in r.reason


def test_tax_04_internet_failure_flags_with_detail():
    online = OnlineCheck(status=OnlineStatus.UNAVAILABLE, detail="connection timed out")
    r = run(challan(online=online))["TAX-04"]
    assert r.outcome is Outcome.FLAG
    assert "internet check failed: connection timed out" in r.reason


@pytest.mark.parametrize("online", [None, OnlineCheck(status=OnlineStatus.NOT_RUN)])
def test_tax_04_online_not_run_flags(online):
    r = run(challan(online=online))["TAX-04"]
    assert r.outcome is Outcome.FLAG
    assert "not verified online: online checks not enabled" in r.reason


def test_tax_04_missing_challan_number_flags_before_online_result():
    r = run(challan(number=None, online=OnlineCheck(status=OnlineStatus.NOT_FOUND)))["TAX-04"]
    assert r.outcome is Outcome.FLAG
    assert "challan number not found" in r.reason


def test_tax_04_low_confidence_challan_number_flags():
    r = run(challan(number_confidence=LOW))["TAX-04"]
    assert r.outcome is Outcome.FLAG
    assert "low OCR confidence" in r.reason


def test_tax_04_verified_but_printed_amount_missing_flags():
    r = run(challan(printed=None))["TAX-04"]
    assert r.outcome is Outcome.FLAG
    assert "printed amount was not found" in r.reason


def test_tax_04_verified_but_printed_amount_unreliable_flags_not_fails():
    online = OnlineCheck(status=OnlineStatus.VERIFIED, amount=Decimal("1500"))
    r = run(challan(online=online, amount_confidence=LOW))["TAX-04"]
    assert r.outcome is Outcome.FLAG
    assert "low OCR confidence" in r.reason


def test_tax_04_verified_but_website_amount_missing_flags():
    r = run(challan(online=OnlineCheck(status=OnlineStatus.VERIFIED)))["TAX-04"]
    assert r.outcome is Outcome.FLAG
    assert "website showed no amount" in r.reason

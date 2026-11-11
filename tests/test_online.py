"""Online checks (ACAD-01 e-Apostille, TAX-04 challan). No network: every HTTP call goes to
a fake that serves pages shaped like the real sites' answers. All numbers are fictional."""

import html
import json
from datetime import date
from decimal import Decimal

import pytest
from builders import apostille, case_file, complete_case_documents, ex

from hklv_online import achallan_number, apostille_id, apply_online_checks, check_apostille, check_challan
from hklv_online.checks import ACHALLAN_HOST, APOSTILLE_HOST, http_fetch
from hklv_rules.engine import evaluate_case
from hklv_rules.models import IncomeTaxChallan, OnlineStatus, Outcome

REAL_ID = "100000000001"
URL = f"https://{APOSTILLE_HOST}/application-details/{REAL_ID}"


def inertia(component: str, props: dict) -> str:
    page = {"component": component, "props": {"errors": {}, "auth": {}, "flash": {}, **props}, "url": "/x"}
    return f'<html><body><div id="app" data-page="{html.escape(json.dumps(page))}"></div></body></html>'


FOUND = inertia("Application/QrVerify", {"redirect_url": f"https://{APOSTILLE_HOST}/verify/abc123token"})
NOT_FOUND = inertia("Application/Details", {"apostileError": "আপনার অ্যাপোস্টিলটি অ্যাপোস্টিল সার্ভিস ডিরেক্টরি থেকে খুঁজুন"})


def challan_page(obj: dict) -> str:
    return f"<html><body><span class='total-amount'></span><script> var obj = {json.dumps(obj)};\n $('body').hide();</script></body></html>"


CHALLAN_NO = "2526-0012345678"
CHALLAN_FOUND = challan_page(
    {"ChallanNo": CHALLAN_NO, "Amount": 15000.0, "ChallanDate": "05-09-2026", "IsRefundRequested": False, "ErrMessage": None}
)
CHALLAN_MISSING = challan_page({"ChallanNo": None, "Amount": None, "IsRefundRequested": False, "ErrMessage": "no data found"})


class FakeWeb:
    def __init__(self, pages: dict[str, tuple[int, str]] | None = None, error: Exception | None = None):
        self.pages, self.error, self.asked = pages or {}, error, []

    def __call__(self, url: str) -> tuple[int, str]:
        self.asked.append(url)
        if self.error:
            raise self.error
        return self.pages.get(url, (404, ""))


# --- e-Apostille -------------------------------------------------------------------------


def test_existing_apostille_is_verified():
    web = FakeWeb({URL: (200, FOUND)})
    check = check_apostille(URL, web)
    assert check.status is OnlineStatus.VERIFIED and REAL_ID in check.detail
    assert web.asked == [URL]


def test_unknown_apostille_is_not_found():
    check = check_apostille(URL, FakeWeb({URL: (200, NOT_FOUND)}))
    assert check.status is OnlineStatus.NOT_FOUND


@pytest.mark.parametrize(
    "web",
    [
        FakeWeb({URL: (503, "")}),
        FakeWeb({URL: (403, "Forbidden")}),
        FakeWeb({URL: (200, "<html>maintenance</html>")}),
        FakeWeb({URL: (200, inertia("Application/QrVerify", {"redirect_url": "https://evil.example/verify/x"}))}),
        FakeWeb(error=TimeoutError("timed out")),
        FakeWeb(error=OSError("no route to host")),
    ],
)
def test_anything_unexpected_is_unavailable_never_a_verdict(web):
    assert check_apostille(URL, web).status is OnlineStatus.UNAVAILABLE


@pytest.mark.parametrize(
    "qr",
    [
        "https://apostille.mygov.bd.evil.example/application-details/100000000001",
        "http://apostille.mygov.bd/application-details/100000000001",
        "https://evil.example/?next=https://apostille.mygov.bd/application-details/1",
        "https://apostille.mygov.bd/admin/delete",
        "javascript:alert(1)",
        "",
        None,
    ],
)
def test_untrusted_qr_content_is_never_opened(qr):
    web = FakeWeb()
    check = check_apostille(qr, web)
    assert check.status is OnlineStatus.UNAVAILABLE and web.asked == []


def test_the_official_url_is_rebuilt_not_copied_from_the_qr():
    web = FakeWeb({URL: (200, FOUND)})
    check_apostille(URL + "/", web)  # trailing slash, but also any oddity, never reaches the request
    assert web.asked == [URL]
    assert apostille_id(f"https://APOSTILLE.MYGOV.BD/application-details/{REAL_ID}") == REAL_ID


def test_http_fetch_refuses_non_official_hosts_before_any_request():
    with pytest.raises(ValueError):
        http_fetch("https://example.com/")
    with pytest.raises(ValueError):
        http_fetch(f"http://{APOSTILLE_HOST}/application-details/{REAL_ID}")


def test_redirects_off_the_official_hosts_are_refused():
    import urllib.error

    from hklv_online.checks import _OfficialHostsOnly

    handler = _OfficialHostsOnly()
    with pytest.raises(urllib.error.HTTPError):
        handler.redirect_request(None, None, 302, "Found", {}, "https://evil.example/x")


# --- Challan -----------------------------------------------------------------------------

CHALLAN_URL = f"https://{ACHALLAN_HOST}/acs/General/PrintChallanSlipDetailsHTML?challanNo={CHALLAN_NO}"


@pytest.mark.parametrize("raw,number", [(CHALLAN_NO, CHALLAN_NO), ("Challan No: 2526 - 0012345678", CHALLAN_NO), ("1234567", None), (None, None)])
def test_achallan_number(raw, number):
    assert achallan_number(raw) == number


def test_existing_challan_returns_the_websites_amount():
    check = check_challan(CHALLAN_NO, FakeWeb({CHALLAN_URL: (200, CHALLAN_FOUND)}))
    assert check.status is OnlineStatus.VERIFIED and check.amount == Decimal("15000.0")


def test_unknown_challan_is_not_found():
    assert check_challan(CHALLAN_NO, FakeWeb({CHALLAN_URL: (200, CHALLAN_MISSING)})).status is OnlineStatus.NOT_FOUND


def test_refund_requested_challan_is_not_valid():
    page = challan_page({"ChallanNo": CHALLAN_NO, "Amount": 15000, "IsRefundRequested": True})
    check = check_challan(CHALLAN_NO, FakeWeb({CHALLAN_URL: (200, page)}))
    assert check.status is OnlineStatus.NOT_FOUND and "refund" in check.detail


@pytest.mark.parametrize(
    "page",
    [
        challan_page({"ChallanNo": "2526-0099999999", "Amount": 15000}),  # answered for another challan
        challan_page({"ChallanNo": CHALLAN_NO, "Amount": None}),  # no readable amount
        challan_page({"ChallanNo": None, "ErrMessage": "server busy"}),
        "<html>no data object</html>",
    ],
)
def test_odd_challan_answers_are_unavailable(page):
    assert check_challan(CHALLAN_NO, FakeWeb({CHALLAN_URL: (200, page)})).status is OnlineStatus.UNAVAILABLE


def test_bank_counter_challans_are_left_for_manual_review_without_a_request():
    web = FakeWeb()
    check = check_challan("CH-778899", web)
    assert check.status is OnlineStatus.UNAVAILABLE and web.asked == []


# --- Whole case -> rules -----------------------------------------------------------------


def test_apply_online_checks_feeds_acad_01():
    docs = [d for d in complete_case_documents()]
    docs = [d.model_copy(update={"online": None}) if d.kind == "e_apostille" else d for d in docs]
    case = case_file(*docs)
    urls = {d.qr_url for d in case.documents if d.kind == "e_apostille"}
    checked = apply_online_checks(case, FakeWeb({u: (200, FOUND) for u in urls}), pause=0)
    verdict = evaluate_case(checked)
    acad_01 = [r for r in verdict.results if r.rule_id == "ACAD-01"]
    assert acad_01 and all(r.outcome is Outcome.PASS for r in acad_01)
    assert verdict.outcome is Outcome.PASS


def test_apostille_unknown_to_the_register_fails_acad_01():
    case = case_file(*[d for d in complete_case_documents() if d.kind != "e_apostille"], apostille(online=None))
    checked = apply_online_checks(case, FakeWeb({URL: (200, NOT_FOUND)}), pause=0)
    [r] = [x for x in evaluate_case(checked).results if x.rule_id == "ACAD-01"]
    assert r.outcome is Outcome.FAIL


def test_site_down_flags_acad_01():
    case = case_file(apostille(online=None))
    checked = apply_online_checks(case, FakeWeb(error=OSError("down")), pause=0)
    [r] = [x for x in evaluate_case(checked).results if x.rule_id == "ACAD-01"]
    assert r.outcome is Outcome.FLAG


def test_challan_amount_mismatch_fails_tax_04():
    challan = IncomeTaxChallan(doc_id="challan", challan_number=ex(CHALLAN_NO), printed_amount=ex(Decimal("12000")))
    checked = apply_online_checks(case_file(challan), FakeWeb({CHALLAN_URL: (200, CHALLAN_FOUND)}), pause=0)
    [r] = [x for x in evaluate_case(checked).results if x.rule_id == "TAX-04"]
    assert r.outcome is Outcome.FAIL


def test_challan_amount_match_passes_tax_04():
    challan = IncomeTaxChallan(doc_id="challan", challan_number=ex(CHALLAN_NO), printed_amount=ex(Decimal("15000")))
    checked = apply_online_checks(case_file(challan), FakeWeb({CHALLAN_URL: (200, CHALLAN_FOUND)}), pause=0)
    [r] = [x for x in evaluate_case(checked).results if x.rule_id == "TAX-04"]
    assert r.outcome is Outcome.PASS


def test_offline_pipeline_leaves_online_results_empty():
    from reading_builders import make_page, qr

    from hklv_ocr.reading import CaseReading
    from hklv_pipeline import evaluate_reading

    page = make_page(["e-APOSTILLE", "Convention de La Haye"], barcodes=[qr(URL)])
    web = FakeWeb({URL: (200, FOUND)})
    offline = evaluate_reading(CaseReading(pages=(page,)), case_id="c", evaluation_date=date(2026, 11, 11))
    assert offline.case.documents[0].online is None
    online = evaluate_reading(CaseReading(pages=(page,)), case_id="c", evaluation_date=date(2026, 11, 11), online=True, fetch=web)
    assert online.case.documents[0].online.status is OnlineStatus.VERIFIED and web.asked == [URL]
    assert "online" in online.seconds


# --- review regressions: hostile or broken input must give UNAVAILABLE (FLAG), never crash ---


@pytest.mark.parametrize(
    "qr",
    ["https://[apostille.mygov.bd/application-details/100000000001", "https://apostille.mygov.bd\uff03@x/application-details/1"],
)
def test_malformed_qr_url_never_crashes_and_acad_01_still_judges_it(qr):
    web = FakeWeb()
    case = case_file(apostille(url=qr, online=None))
    checked = apply_online_checks(case, web, pause=0)
    assert web.asked == []
    [r] = [x for x in evaluate_case(checked).results if x.rule_id == "ACAD-01"]
    assert r.outcome in (Outcome.FAIL, Outcome.FLAG)


@pytest.mark.parametrize("error", [__import__("http.client").client.IncompleteRead(b"x", 10), __import__("http.client").client.BadStatusLine("GARBAGE"), LookupError("bogus"), RuntimeError("?")])
def test_any_transport_failure_is_unavailable(error):
    assert check_apostille(URL, FakeWeb(error=error)).status is OnlineStatus.UNAVAILABLE
    assert check_challan(CHALLAN_NO, FakeWeb(error=error)).status is OnlineStatus.UNAVAILABLE


def test_hostile_json_is_unavailable():
    deep = "[" * 200000
    page = f'<div data-page="{deep}"></div>'
    huge_int = "9" * 5000
    assert check_apostille(URL, FakeWeb({URL: (200, page)})).status is OnlineStatus.UNAVAILABLE
    assert check_apostille(URL, FakeWeb({URL: (200, f'<div data-page="{{&quot;props&quot;: {huge_int}}}"></div>')})).status is OnlineStatus.UNAVAILABLE
    challan = f"<script>var obj = {{\"ChallanNo\": \"{CHALLAN_NO}\", \"Amount\": {huge_int}}};</script>"
    assert check_challan(CHALLAN_NO, FakeWeb({CHALLAN_URL: (200, challan)})).status is OnlineStatus.UNAVAILABLE


@pytest.mark.parametrize(
    "page",
    [
        inertia("Application/QrVerify", {"apostileError": "x"}),  # error prop on the wrong component
        inertia("Something/Else", {"apostileError": "x"}),
        inertia("Application/Details", {"apostileError": ["x"]}),
        inertia("Application/QrVerify", {"redirect_url": f"https://{APOSTILLE_HOST}/verify/"}),  # empty token
    ],
)
def test_only_the_exact_register_answers_count(page):
    assert check_apostille(URL, FakeWeb({URL: (200, page)})).status is OnlineStatus.UNAVAILABLE


def test_non_dict_props_is_unavailable():
    page = f'<div data-page="{html.escape(json.dumps({"component": "Application/QrVerify", "props": ["x"]}))}"></div>'
    assert check_apostille(URL, FakeWeb({URL: (200, page)})).status is OnlineStatus.UNAVAILABLE


@pytest.mark.parametrize("flag,status", [(True, OnlineStatus.NOT_FOUND), (False, OnlineStatus.VERIFIED), (None, OnlineStatus.VERIFIED), ("false", OnlineStatus.UNAVAILABLE), (0, OnlineStatus.UNAVAILABLE), ("N", OnlineStatus.UNAVAILABLE)])
def test_refund_flag_is_read_strictly(flag, status):
    page = challan_page({"ChallanNo": CHALLAN_NO, "Amount": 15000, "IsRefundRequested": flag})
    assert check_challan(CHALLAN_NO, FakeWeb({CHALLAN_URL: (200, page)})).status is status


def test_official_host_link_without_application_number_is_reported_not_skipped():
    web = FakeWeb()
    case = case_file(apostille(url=f"https://{APOSTILLE_HOST}/some/other/page", online=None))
    checked = apply_online_checks(case, web, pause=0)
    assert web.asked == []
    doc = next(d for d in checked.documents if d.kind == "e_apostille")
    assert doc.online.status is OnlineStatus.UNAVAILABLE and "application-details" in doc.online.detail
    [r] = [x for x in evaluate_case(checked).results if x.rule_id == "ACAD-01"]
    assert r.outcome is Outcome.FLAG and "not enabled" not in r.reason


def test_http_fetch_caps_size_and_survives_unknown_charset(monkeypatch):
    import io

    import hklv_online.checks as checks

    class Response(io.BytesIO):
        status = 200

        def __init__(self, data, charset):
            super().__init__(data)
            self.headers = type("H", (), {"get_content_charset": staticmethod(lambda: charset)})()

    class Opener:
        def __init__(self, data, charset="utf-8"):
            self.data, self.charset = data, charset

        def open(self, request, timeout):
            return Response(self.data, self.charset)

    monkeypatch.setattr(checks, "_opener", Opener("abc".encode(), "bogus-charset"))
    assert checks.http_fetch(URL) == (200, "abc")
    monkeypatch.setattr(checks, "_opener", Opener(b"x" * (checks.MAX_RESPONSE_BYTES + 70000)))
    with pytest.raises(ValueError):
        checks.http_fetch(URL)

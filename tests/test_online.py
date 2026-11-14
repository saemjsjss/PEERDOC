"""Online checks (ACAD-01 e-Apostille, TAX-04 challan). No network: every HTTP call goes to
a fake that serves pages shaped like the real sites' answers. All numbers are fictional."""

import html
import json
from datetime import date
from decimal import Decimal

import pytest
from builders import apostille, case_file, complete_case_documents, ex, register_copy

from hklv_online import achallan_number, apostille_id, apply_online_checks, check_apostille, check_challan
from hklv_online import register_copy as register_copy_online
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
    checked = apply_online_checks(
        case,
        FakeWeb({u: (200, FOUND) for u in urls}),
        pause=0,
        post=lambda url: (200, REGISTER_JSON),
        get_bytes=lambda url: (200, PNG),
        read_register=lambda images: tuple(register_copy(title=t) for t, _ in images),
    )
    verdict = evaluate_case(checked)
    acad_01 = [r for r in verdict.results if r.rule_id == "ACAD-01"]
    assert acad_01 and all(r.outcome is Outcome.PASS for r in acad_01), acad_01
    assert all("student's name" in r.reason for r in acad_01)
    assert verdict.outcome is Outcome.PASS
    online = [d.online for d in checked.documents if d.kind == "e_apostille"]
    assert all("was read for the owner check" in o.detail for o in online), online


# --- RULES-v10: the register's own copy ----------------------------------------------------

PNG = b"\x89PNG\r\n\x1a\n fictional image"
_FILE = "https://api.apostille.mygov.bd/api/v1/secure-external-file/eyJmaWN0aW9uYWwiOjF9.abc123"
REGISTER_JSON = (
    '{"status":"success","data":{"details":{"apostille_date":"2026-02-18","attachment":['
    '{"title":"Certificate (ForAttestation)*","attachement_url":"' + _FILE + '"},'
    '{"title":"Transcript (ForAttestation)*","attachement_url":"' + _FILE + '"}]}}}'
)


def test_register_copy_downloads_and_reads_each_page():
    seen = []
    when, pages, note = register_copy_online(
        "100000000001",
        post=lambda url: (seen.append(url), (200, REGISTER_JSON))[1],
        get_bytes=lambda url: (200, PNG),
        read_register=lambda images: tuple(register_copy(title=t) for t, _ in images),
    )
    assert seen == ["https://api.apostille.mygov.bd/api/v1/application-details/100000000001"]
    assert when == date(2026, 2, 18) and note == ""
    assert [p.title for p in pages] == ["Certificate (ForAttestation)*", "Transcript (ForAttestation)*"]


def test_register_page_links_to_other_hosts_are_never_opened():
    body = REGISTER_JSON.replace("api.apostille.mygov.bd", "evil.example")
    opened = []
    _, pages, note = register_copy_online(
        "100000000001", lambda url: (200, body), lambda url: (opened.append(url), (200, PNG))[1], lambda i: ()
    )
    assert opened == [] and pages == () and "no document pages" in note


def test_register_page_that_is_not_an_image_is_not_read():
    _, pages, note = register_copy_online(
        "100000000001", lambda url: (200, REGISTER_JSON), lambda url: (200, b"<html>"), lambda i: 1 / 0
    )
    assert pages == () and "not an image" in note


def test_without_ocr_the_register_copy_is_not_read():
    _, pages, note = register_copy_online("100000000001", lambda url: (200, REGISTER_JSON), lambda url: (200, PNG), None)
    assert pages == () and "OCR is not available" in note


def test_printed_number_is_looked_up_when_the_qr_is_unreadable():
    web = FakeWeb({URL: (200, FOUND)})
    a = apostille(url=None, online=None, printed=URL.rsplit("/", 1)[-1])
    [doc] = [d for d in apply_online_checks(case_file(a), web, pause=0).documents if d.kind == "e_apostille"]
    assert web.asked == [URL]
    assert doc.online.status is OnlineStatus.VERIFIED and doc.online.number_source == "printed"
    assert "its copy was not read (register copy not fetched in this run)" in doc.online.detail


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

    monkeypatch.setattr(checks, "_opener", Opener(b"abc", "bogus-charset"))
    assert checks.http_fetch(URL) == (200, "abc")
    monkeypatch.setattr(checks, "_opener", Opener(b"x" * (checks.MAX_RESPONSE_BYTES + 70000)))
    with pytest.raises(ValueError):
        checks.http_fetch(URL)


def test_http_fetch_deadline_bounds_a_trickling_server(monkeypatch):
    import hklv_online.checks as checks

    class Trickle:
        status = 200
        headers = None

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read1(self, n):
            return b"x"  # one byte per read, forever

        def read(self, n=-1):
            raise AssertionError("read() waits for n bytes; read1() must be used")

    clock = iter(range(0, 10_000, 5))
    monkeypatch.setattr(checks.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(checks, "_opener", type("O", (), {"open": lambda self, request, timeout: Trickle()})())
    with pytest.raises(TimeoutError):
        checks.http_fetch(URL)


def test_http_fetch_closes_error_responses(monkeypatch):
    import io
    import urllib.error

    import hklv_online.checks as checks

    body = io.BytesIO(b"error page")

    class Opener:
        def open(self, request, timeout):
            raise urllib.error.HTTPError(URL, 503, "busy", {}, body)

    monkeypatch.setattr(checks, "_opener", Opener())
    assert checks.http_fetch(URL) == (503, "")
    assert body.closed


def test_challan_amount_with_thousands_separator_is_read():
    # The live site sends the amount as a string with a comma (seen 2026-11-12).
    page = challan_page({"ChallanNo": CHALLAN_NO, "Amount": "3,000.00", "IsRefundRequested": False, "ErrMessage": None})
    check = check_challan(CHALLAN_NO, FakeWeb({CHALLAN_URL: (200, page)}))
    assert check.status is OnlineStatus.VERIFIED and check.amount == Decimal("3000")


def test_register_copy_beyond_the_page_cap_is_marked_incomplete(monkeypatch):
    monkeypatch.setattr("hklv_online.checks.MAX_REGISTER_PAGES", 1)
    _, pages, note = register_copy_online(
        "100000000001", lambda url: (200, REGISTER_JSON), lambda url: (200, PNG),
        lambda images: tuple(register_copy(title=t) for t, _ in images),
    )
    assert len(pages) == 1 and note == "only the first 1 of 2 register pages were read"


def test_register_page_ocr_could_not_read_is_marked_incomplete():
    _, pages, note = register_copy_online(
        "100000000001", lambda url: (200, REGISTER_JSON), lambda url: (200, PNG),
        lambda images: (register_copy(title=images[0][0]),),
    )
    assert len(pages) == 1 and note == "1 of 2 register pages could not be read"


def test_register_outage_after_verified_keeps_verified_and_flags_acad_01():
    def down(url):
        raise OSError("down")

    a = apostille(online=None)
    checked = apply_online_checks(
        case_file(a), FakeWeb({URL: (200, FOUND)}), pause=0, post=down, get_bytes=lambda url: (200, PNG),
        read_register=lambda images: (),
    )
    [doc] = [d for d in checked.documents if d.kind == "e_apostille"]
    assert doc.online.status is OnlineStatus.VERIFIED and "could not be reached" in doc.online.register_note
    [r] = [r for r in evaluate_case(checked).results if r.rule_id == "ACAD-01"]
    assert r.outcome is Outcome.FLAG and "owner was not checked" in r.reason


def test_register_attachment_that_is_not_a_list_is_no_pages():
    body = REGISTER_JSON.replace('"attachment":[', '"attachment":7,"x":[')
    _, pages, note = register_copy_online("100000000001", lambda url: (200, body), lambda url: (200, PNG), lambda i: ())
    assert pages == () and "no document pages" in note

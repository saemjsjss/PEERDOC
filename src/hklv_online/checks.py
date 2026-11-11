"""Check e-Apostilles and automated challans on the official sites.

Behaviour measured on the live sites (2026-11-11):

e-Apostille, https://apostille.mygov.bd/application-details/<number> (the URL in the QR):
    an existing apostille -> Inertia page component "Application/QrVerify" whose
        redirect_url is an official https://apostille.mygov.bd/verify/<token> record link;
    no such apostille -> component "Application/Details" with an "apostileError" message
        (Bangla: "find your apostille in the apostille service directory").
    The record page behind /verify/<token> refuses automated access (HTTP 403), and we do
    not try to get around that. So VERIFIED means "the official register has an apostille
    with this application number", not "its contents match the scan".

Automated challan (A-challan), as embedded by challanverification.finance.gov.bd:
    https://www.achallan.gov.bd/acs/General/PrintChallanSlipDetailsHTML?challanNo=<YYYY-NNNNNNNNNN>
    carries the challan as JSON in `var obj = {...};`: ChallanNo, Amount, ChallanDate,
    IsRefundRequested ... For an unknown number: ChallanNo null, ErrMessage "no data found".
    Older bank-counter challans need bank, branch and date on the site's form; they are not
    checked automatically (UNAVAILABLE -> FLAG for manual review).

Safety:
    * QR content is untrusted. We never open the QR's own URL: we take the application
      number from a link on the official host and build the official URL ourselves.
    * Requests go only to the two official hosts, over https; a redirect to any other
      host is refused.
    * Anything unexpected (network error, timeout, HTTP error, a page we don't recognise)
      is UNAVAILABLE, which the rules treat as FLAG. Only a clear "no such record" answer
      is NOT_FOUND (FAIL).
"""

from __future__ import annotations

import codecs
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from decimal import Decimal, InvalidOperation

from hklv_rules.models import CaseFile, EApostille, IncomeTaxChallan, OnlineCheck, OnlineStatus

APOSTILLE_HOST = "apostille.mygov.bd"
ACHALLAN_HOST = "www.achallan.gov.bd"
ALLOWED_HOSTS = frozenset({APOSTILLE_HOST, ACHALLAN_HOST})
# Identify ourselves honestly; the sites answer this plain request normally.
USER_AGENT = "Mozilla/5.0 (HKLV document verification)"
TIMEOUT_SECONDS = 20  # per socket operation
TOTAL_DEADLINE_SECONDS = 45  # for the whole download, however slowly bytes trickle in
# (checked after every read; a read returns as soon as any bytes arrive, so a trickling
# server is cut off at TOTAL_DEADLINE_SECONDS + at most one TIMEOUT_SECONDS wait)
MAX_RESPONSE_BYTES = 2_000_000  # the real pages are ~40 KB
PAUSE_BETWEEN_REQUESTS = 0.5  # be polite to small government servers

# fetch(url) -> (HTTP status, body text). Injectable so tests never touch the network.
Fetch = Callable[[str], tuple[int, str]]


class _OfficialHostsOnly(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only if it stays on an allowed host over https."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlparse(newurl)
        if target.scheme != "https" or (target.hostname or "").lower() not in ALLOWED_HOSTS:
            raise urllib.error.HTTPError(newurl, code, f"refused redirect to {target.hostname}", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_OfficialHostsOnly())


def http_fetch(url: str) -> tuple[int, str]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in ALLOWED_HOSTS:
        raise ValueError(f"not an allowed official URL: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    started = time.monotonic()
    try:
        with _opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            body = bytearray()
            # read1: whatever has arrived (up to 64 KB), not "wait until 64 KB arrived".
            while chunk := response.read1(65536):
                body += chunk
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ValueError(f"response larger than {MAX_RESPONSE_BYTES} bytes")
                if time.monotonic() - started > TOTAL_DEADLINE_SECONDS:
                    raise TimeoutError(f"download took longer than {TOTAL_DEADLINE_SECONDS} s")
            charset = response.headers.get_content_charset() or "utf-8"
            try:
                codecs.lookup(charset)
            except LookupError:
                charset = "utf-8"
            return response.status, bytes(body).decode(charset, errors="replace")
    except urllib.error.HTTPError as e:
        e.close()  # it holds the connection open otherwise
        return e.code, ""


def _unavailable(detail: str) -> OnlineCheck:
    return OnlineCheck(status=OnlineStatus.UNAVAILABLE, detail=detail)


def _get(fetch: Fetch, url: str) -> tuple[int, str] | OnlineCheck:
    # Any failure to fetch (network, timeout, truncated body, bad status line, odd charset,
    # oversized answer) is "could not check", never a verdict.
    try:
        return fetch(url)
    except Exception as e:  # noqa: BLE001
        return _unavailable(f"site could not be reached ({type(e).__name__}: {e})")


def _parse_json(text: str) -> object | None:
    """JSON from an untrusted page; None instead of any parser exception (incl. hostile
    nesting depth or oversized integers)."""
    try:
        value, _ = json.JSONDecoder().raw_decode(text)
        return value
    except (ValueError, RecursionError):
        return None


# --- e-Apostille ---------------------------------------------------------------------------

_APOSTILLE_PATH = re.compile(r"^/application-details/(\d{8,20})/?$")


def apostille_id(qr_url: str | None) -> str | None:
    """The application number from an official e-Apostille link, else None."""
    if not qr_url:
        return None
    parsed, host = _parse_url(qr_url)
    if parsed is None or parsed.scheme != "https" or host != APOSTILLE_HOST:
        return None
    m = _APOSTILLE_PATH.match(parsed.path)
    return m.group(1) if m else None


def _parse_url(url: str):
    """(parsed URL, lowercased host) or (None, '') for text urllib can't parse (a forged QR
    such as 'https://[apostille.mygov.bd/...' must not crash the run)."""
    try:
        parsed = urllib.parse.urlparse(url.strip())
        return parsed, (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        return None, ""


def on_apostille_host(qr_url: str | None) -> bool:
    """https link on the official host, whatever its path."""
    if not qr_url:
        return False
    parsed, host = _parse_url(qr_url)
    return parsed is not None and parsed.scheme == "https" and host == APOSTILLE_HOST


def _inertia_page(body: str) -> dict | None:
    m = re.search(r'data-page="([^"]*)"', body)
    if not m:
        return None
    page = _parse_json(html.unescape(m.group(1)))
    return page if isinstance(page, dict) else None


def check_apostille(qr_url: str | None, fetch: Fetch = http_fetch) -> OnlineCheck:
    number = apostille_id(qr_url)
    if number is None:
        return _unavailable("not an official e-Apostille link with an application number; not opened")
    got = _get(fetch, f"https://{APOSTILLE_HOST}/application-details/{number}")
    if isinstance(got, OnlineCheck):
        return got
    status, body = got
    if status != 200:
        return _unavailable(f"site answered HTTP {status}")
    page = _inertia_page(body)
    if page is None:
        return _unavailable("unrecognised answer from the e-Apostille site")
    props = page.get("props")
    if not isinstance(props, dict):
        return _unavailable("unrecognised answer from the e-Apostille site")
    component = page.get("component")
    redirect = props.get("redirect_url")
    if component == "Application/QrVerify" and isinstance(redirect, str):
        target, host = _parse_url(redirect)
        if target is not None and target.scheme == "https" and host == APOSTILLE_HOST and re.fullmatch(r"/verify/[^/]+", target.path):
            return OnlineCheck(
                status=OnlineStatus.VERIFIED,
                detail=f"the official register has e-Apostille {number} (its contents were not compared)",
            )
    error = props.get("apostileError")
    # NOT_FOUND (a FAIL) only for exactly the page the register shows for an unknown number.
    if component == "Application/Details" and isinstance(error, str) and error.strip():
        return OnlineCheck(status=OnlineStatus.NOT_FOUND, detail=f"the official register has no e-Apostille {number}")
    return _unavailable("unrecognised answer from the e-Apostille site")


# --- Automated challan ---------------------------------------------------------------------

_ACHALLAN_NO = re.compile(r"(?<!\d)(\d{4})\s*-\s*(\d{10})(?!\d)")


def achallan_number(text: str | None) -> str | None:
    """'2526-0012345678' (A-challan format) from the extracted challan number, else None."""
    if not text:
        return None
    m = _ACHALLAN_NO.search(text)
    return f"{m.group(1)}-{m.group(2)}" if m else None


def _challan_object(body: str) -> dict | None:
    i = body.find("var obj")
    if i < 0:
        return None
    start = body.find("{", i)
    if start < 0:
        return None
    obj = _parse_json(body[start:])
    return obj if isinstance(obj, dict) else None


def check_challan(challan_no: str | None, fetch: Fetch = http_fetch) -> OnlineCheck:
    number = achallan_number(challan_no)
    if number is None:
        return _unavailable(
            "not an automated challan number (YYYY-NNNNNNNNNN); bank-counter challans need the "
            "bank, branch and date on challanverification.finance.gov.bd, so check it by hand"
        )
    query = urllib.parse.urlencode({"challanNo": number})
    got = _get(fetch, f"https://{ACHALLAN_HOST}/acs/General/PrintChallanSlipDetailsHTML?{query}")
    if isinstance(got, OnlineCheck):
        return got
    status, body = got
    if status != 200:
        return _unavailable(f"site answered HTTP {status}")
    obj = _challan_object(body)
    if obj is None:
        return _unavailable("unrecognised answer from the challan site")
    site_no = obj.get("ChallanNo")
    if not site_no:
        if "no data" in str(obj.get("ErrMessage") or "").lower():
            return OnlineCheck(status=OnlineStatus.NOT_FOUND, detail=f"the challan system has no challan {number}")
        return _unavailable("unrecognised answer from the challan site")
    if re.sub(r"\D", "", str(site_no)) != re.sub(r"\D", "", number):
        return _unavailable(f"the site answered for a different challan ({site_no})")
    refund = obj.get("IsRefundRequested")
    if refund is True:
        return OnlineCheck(
            status=OnlineStatus.NOT_FOUND,
            detail=f"challan {number} has a refund request and is not valid for any service",
        )
    if refund is not None and refund is not False:  # identity: 0 == False must not slip through
        return _unavailable(f"the challan site showed an unrecognised refund flag ({refund!r})")
    try:
        amount = Decimal(str(obj.get("Amount")).replace(",", ""))  # the site prints "3,000.00"
    except (InvalidOperation, ValueError):
        return _unavailable("the challan site did not show a readable amount")
    if not amount.is_finite():
        return _unavailable("the challan site did not show a readable amount")
    return OnlineCheck(
        status=OnlineStatus.VERIFIED,
        detail=f"challan {number} found, dated {obj.get('ChallanDate') or 'unknown'}",
        amount=amount,
    )


# --- Whole case ------------------------------------------------------------------------------


def apply_online_checks(case: CaseFile, fetch: Fetch = http_fetch, pause: float = PAUSE_BETWEEN_REQUESTS) -> CaseFile:
    """A copy of `case` with every e-Apostille and challan's `online` result filled in.

    Apostilles whose QR isn't an official link are left alone: ACAD-01 judges them without
    opening anything. Blocking (urllib); call it from a worker thread in async code.
    """
    documents = []
    first = True
    for doc in case.documents:
        check = None
        if isinstance(doc, EApostille) and doc.qr_decoded:
            if apostille_id(doc.qr_url):
                check = lambda d=doc: check_apostille(d.qr_url, fetch)  # noqa: E731
            elif on_apostille_host(doc.qr_url):
                # Official site but not an application link we can look up: say so, rather
                # than ACAD-01 reporting "online checks not enabled".
                documents.append(
                    doc.model_copy(
                        update={"online": _unavailable("official site, but not an /application-details/<number> link; not opened")}
                    )
                )
                continue
        elif isinstance(doc, IncomeTaxChallan) and doc.challan_number.found:
            check = lambda d=doc: check_challan(d.challan_number.value, fetch)  # noqa: E731
        if check is None:
            documents.append(doc)
            continue
        if not first and pause:
            time.sleep(pause)
        first = False
        try:
            result = check()
        except Exception as e:  # noqa: BLE001  (defence in depth: a check must never crash the run)
            result = _unavailable(f"online check failed unexpectedly ({type(e).__name__})")
        documents.append(doc.model_copy(update={"online": result}))
    return case.model_copy(update={"documents": tuple(documents)})

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

e-Apostille register details (RULES-v10, measured 2026-11-14),
POST https://api.apostille.mygov.bd/api/v1/application-details/<number> (the public lookup
behind mofa-servicedirectory.apostille.mygov.bd; GET answers 405):
    JSON data.details: apostille_date, application_type, and "attachment" (sic) entries with
    a title ("HSC Transcript (ForAttestation)*") and an "attachement_url" to the page image
    on api.apostille.mygov.bd/api/v1/secure-external-file/<signed token>. The token is tied
    to the requesting IP and expires, so images are downloaded at once and never stored.
    ACAD-01 reads those images by OCR to check the copy is the student's.

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
from datetime import date
from decimal import Decimal, InvalidOperation

from hklv_rules.models import CaseFile, EApostille, IncomeTaxChallan, OnlineCheck, OnlineStatus, RegisterPage

APOSTILLE_HOST = "apostille.mygov.bd"
# RULES-v10: the register's JSON lookup behind mofa-servicedirectory.apostille.mygov.bd
REGISTER_API_HOST = "api.apostille.mygov.bd"
ACHALLAN_HOST = "www.achallan.gov.bd"
ALLOWED_HOSTS = frozenset({APOSTILLE_HOST, REGISTER_API_HOST, ACHALLAN_HOST})
# Identify ourselves honestly; the sites answer this plain request normally.
USER_AGENT = "Mozilla/5.0 (HKLV document verification)"
TIMEOUT_SECONDS = 20  # per socket operation
TOTAL_DEADLINE_SECONDS = 45  # for the whole download, however slowly bytes trickle in
# (checked after every read; a read returns as soon as any bytes arrive, so a trickling
# server is cut off at TOTAL_DEADLINE_SECONDS + at most one TIMEOUT_SECONDS wait)
MAX_RESPONSE_BYTES = 2_000_000  # the real pages are ~40 KB
MAX_IMAGE_BYTES = 15_000_000  # a register page image (PNG) is ~1-3 MB
MAX_REGISTER_PAGES = 10
PAUSE_BETWEEN_REQUESTS = 0.5  # be polite to small government servers

# fetch(url) -> (HTTP status, body text). Injectable so tests never touch the network.
Fetch = Callable[[str], tuple[int, str]]
# RULES-v10 register copy: POST for the JSON, GET for the page images, and an OCR step
# (title, image bytes) -> RegisterPage that the pipeline supplies (it owns the OCR reader).
Post = Callable[[str], tuple[int, str]]
GetBytes = Callable[[str], tuple[int, bytes]]
ReadRegister = Callable[[list[tuple[str, bytes]]], tuple[RegisterPage, ...]]


class _OfficialHostsOnly(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only if it stays on an allowed host over https."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlparse(newurl)
        if target.scheme != "https" or (target.hostname or "").lower() not in ALLOWED_HOSTS:
            raise urllib.error.HTTPError(newurl, code, f"refused redirect to {target.hostname}", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_OfficialHostsOnly())


def _download(url: str, method: str, accept: str, max_bytes: int) -> tuple[int, bytes, str]:
    """(status, body bytes, charset) from an allowed official https URL, with size and time limits."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in ALLOWED_HOSTS:
        raise ValueError(f"not an allowed official URL: {url}")
    request = urllib.request.Request(
        url, method=method, data=b"" if method == "POST" else None, headers={"User-Agent": USER_AGENT, "Accept": accept}
    )
    started = time.monotonic()
    try:
        with _opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            body = bytearray()
            # read1: whatever has arrived (up to 64 KB), not "wait until 64 KB arrived".
            while chunk := response.read1(65536):
                body += chunk
                if len(body) > max_bytes:
                    raise ValueError(f"response larger than {max_bytes} bytes")
                if time.monotonic() - started > TOTAL_DEADLINE_SECONDS:
                    raise TimeoutError(f"download took longer than {TOTAL_DEADLINE_SECONDS} s")
            charset = response.headers.get_content_charset() or "utf-8"
            try:
                codecs.lookup(charset)
            except LookupError:
                charset = "utf-8"
            return response.status, bytes(body), charset
    except urllib.error.HTTPError as e:
        e.close()  # it holds the connection open otherwise
        return e.code, b"", "utf-8"


def http_fetch(url: str) -> tuple[int, str]:
    status, body, charset = _download(url, "GET", "text/html", MAX_RESPONSE_BYTES)
    return status, body.decode(charset, errors="replace")


def http_post_json(url: str) -> tuple[int, str]:
    """The register API answers POST only (GET is 405)."""
    status, body, charset = _download(url, "POST", "application/json", MAX_RESPONSE_BYTES)
    return status, body.decode(charset, errors="replace")


def http_get_bytes(url: str) -> tuple[int, bytes]:
    status, body, _ = _download(url, "GET", "image/*", MAX_IMAGE_BYTES)
    return status, body


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
    return check_apostille_number(number, fetch)


def check_apostille_number(number: str, fetch: Fetch = http_fetch) -> OnlineCheck:
    """Does the register have this application number? (The QR's number, or the printed No.)"""
    if not re.fullmatch(r"\d{8,20}", number or ""):
        return _unavailable("not an apostille number; not looked up")
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
                detail=f"the official register has e-Apostille {number}",
            )
    error = props.get("apostileError")
    # NOT_FOUND (a FAIL) only for exactly the page the register shows for an unknown number.
    if component == "Application/Details" and isinstance(error, str) and error.strip():
        return OnlineCheck(status=OnlineStatus.NOT_FOUND, detail=f"the official register has no e-Apostille {number}")
    return _unavailable("unrecognised answer from the e-Apostille site")


# --- e-Apostille register copy (RULES-v10) --------------------------------------------------

_REGISTER_FILE = re.compile(r"^/api/v1/secure-external-file/[A-Za-z0-9_=.%-]+$")
_IMAGE_MAGIC = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")


def register_copy(
    number: str, post: Post, get_bytes: GetBytes, read_register: ReadRegister | None
) -> tuple[date | None, tuple[RegisterPage, ...], str]:
    """(apostille date, the register's pages read by OCR, note) for a number the register
    has. The note says why pages are missing; it is empty when every page was read.

    The page links are signed for this computer and expire, so they are downloaded at once
    and never stored or shown."""
    try:
        status, body = post(f"https://{REGISTER_API_HOST}/api/v1/application-details/{number}")
    except Exception as e:  # noqa: BLE001
        return None, (), f"register could not be reached ({type(e).__name__})"
    obj = _parse_json(body) if status == 200 else None
    data = obj.get("data") if isinstance(obj, dict) else None
    details = data.get("details") if isinstance(data, dict) else None
    if not isinstance(details, dict):
        return None, (), f"register gave no details (HTTP {status})"
    try:
        when = date.fromisoformat(str(details.get("apostille_date") or "")[:10])
    except ValueError:
        when = None
    files: list[tuple[str, str]] = []
    attachments = details.get("attachment")
    for a in attachments if isinstance(attachments, list) else []:
        url = a.get("attachement_url") if isinstance(a, dict) else None  # the API's spelling
        if not isinstance(url, str):
            continue
        u = urllib.parse.urlparse(url)
        if u.scheme == "https" and (u.hostname or "").lower() == REGISTER_API_HOST and _REGISTER_FILE.match(u.path):
            files.append((str(a.get("title") or "").strip()[:200], url))
    if not files:
        return when, (), "register lists no document pages"
    if read_register is None:
        return when, (), "register pages not read (OCR is not available in this run)"
    images: list[tuple[str, bytes]] = []
    for title, url in files[:MAX_REGISTER_PAGES]:
        try:
            st, img = get_bytes(url)
        except Exception as e:  # noqa: BLE001
            return when, (), f"register page could not be downloaded ({type(e).__name__})"
        if st != 200 or not img.startswith(_IMAGE_MAGIC):
            return when, (), f"register page was not an image (HTTP {st})"
        images.append((title, img))
    try:
        pages = tuple(read_register(images))
    except Exception as e:  # noqa: BLE001
        return when, (), f"register pages could not be read ({type(e).__name__})"
    # A non-empty note marks the copy incomplete, so ACAD-01 won't FAIL on a page it never saw.
    if len(files) > len(images):
        return when, pages, f"only the first {len(images)} of {len(files)} register pages were read"
    if len(pages) < len(images):
        return when, pages, f"{len(images) - len(pages)} of {len(images)} register pages could not be read"
    return when, pages, ""


def _with_register(check: OnlineCheck, number: str, source: str, post, get_bytes, read_register) -> OnlineCheck:
    update: dict = {"number": number, "number_source": source}
    if check.status is OnlineStatus.VERIFIED:
        if post is None or get_bytes is None:
            update["register_note"] = "register copy not fetched in this run"
        else:
            update["register_date"], update["register_pages"], update["register_note"] = register_copy(
                number, post, get_bytes, read_register
            )
        pages = update.get("register_pages") or ()
        update["detail"] = check.detail + (
            f"; its copy of {len(pages)} document(s) was read for the owner check"
            if pages
            else f"; its copy was not read ({update['register_note'] or 'no pages'})"
        )
    return check.model_copy(update=update)


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


def apply_online_checks(
    case: CaseFile,
    fetch: Fetch = http_fetch,
    pause: float = PAUSE_BETWEEN_REQUESTS,
    *,
    post: Post | None = None,
    get_bytes: GetBytes | None = None,
    read_register: ReadRegister | None = None,
) -> CaseFile:
    """A copy of `case` with every e-Apostille and challan's `online` result filled in.

    Apostilles whose QR isn't an official link are left alone: ACAD-01 judges them without
    opening anything. With no readable QR, the printed No. is looked up instead (RULES-v10).
    `post` / `get_bytes` (None: skipped) fetch the register's own copy of a found apostille,
    and `read_register` OCRs it. Blocking (urllib); call it from a worker thread in async code.
    """

    def apostille(number: str, source: str):
        return lambda: _with_register(check_apostille_number(number, fetch), number, source, post, get_bytes, read_register)

    documents = []
    first = True
    for doc in case.documents:
        check = None
        if isinstance(doc, EApostille) and not doc.qr_decoded and doc.printed_number.found:
            check = apostille(doc.printed_number.value, "printed")
        elif isinstance(doc, EApostille) and doc.qr_decoded:
            if n := apostille_id(doc.qr_url):
                check = apostille(n, "qr")
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

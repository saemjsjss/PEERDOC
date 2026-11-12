"""Rulebook v2.5 section 4.8: Academic certificates (ACAD-01 .. ACAD-05).

Pass 1 only creates academic documents inside an e-Apostille block. In a real submission
every certificate and every transcript has its OWN e-Apostille page right before it:
apostille, SSC certificate, apostille, SSC transcript, apostille, HSC certificate, ...

Interpretations of the rulebook text:
  * ACAD-01: the QR must point (https) at the official e-Apostille host. A different
    scheme or host is an invalid QR -> FAIL. The online check itself is done outside the
    engine; the rule only reads its outcome (site says no such apostille -> FAIL, internet
    or site failure -> FLAG, online checks not enabled -> FLAG).
  * ACAD-02 ("Every e-Apostille MUST be followed by a Certificate AND a Transcript"):
    because each certificate and each transcript has its own apostille, the pairing is
    checked per academic LEVEL: every level with a certificate must also have a
    transcript (missing transcript -> FAIL, as the rulebook says) and, symmetrically,
    every level with a transcript must have a certificate (FAIL). A certificate or
    transcript whose level is missing, unreadable or OTHER can't be paired -> FLAG; while
    such a transcript (certificate) exists, a level whose certificate (transcript) has no
    partner is FLAG instead of FAIL, since the unreadable document may be that partner.
    An e-Apostille whose next document (by page) is not a certificate or transcript,
    or that is the last document, -> FLAG. No academic documents at all -> FLAG, not
    FAIL: academics are not in section 3's required list.
  * ACAD-03: the rulebook only defines the PASS case (a valid track is present). Any
    other combination is left to manual review -> FLAG. Extra levels (e.g. BACHELOR)
    don't spoil a valid track.
  * ACAD-04: a name or DOB mismatch is FLAG (the rulebook says so for this rule, unlike
    5.2's FAIL); a spelling difference covered by a valid affidavit is accepted. Only
    SSC and Dakhil certificates are checked against the passport DOB. When a
    certificate's level can't be read, its DOB still passes if it reliably equals the
    passport DOB; otherwise the rule FLAGs because the DOB check may apply.
  * ACAD-05 (RULES-v2): every certificate and transcript is notarised, judged like every
    other document's notary rule. The e-Apostille page is not checked.
"""

from __future__ import annotations

from datetime import date
from urllib.parse import urlparse

from ..context import EvaluationContext
from ..identity import MatchKind, compare_name
from ..models import (
    AcademicCertificate,
    AcademicLevel,
    AcademicTranscript,
    EApostille,
    Evidence,
    Extracted,
    OnlineStatus,
    Outcome,
    Passport,
    Person,
    RuleResult,
    worst,
)
from ._evidence import ev
from ._shared import notary_rule

ACAD_01, ACAD_02, ACAD_03, ACAD_04, ACAD_05 = "ACAD-01", "ACAD-02", "ACAD-03", "ACAD-04", "ACAD-05"
ALL_RULES = (ACAD_01, ACAD_02, ACAD_03, ACAD_04, ACAD_05)

OFFICIAL_APOSTILLE_HOSTS = ("apostille.mygov.bd",)

VALID_TRACKS: tuple[tuple[AcademicLevel, AcademicLevel], ...] = (
    (AcademicLevel.SSC, AcademicLevel.HSC),
    (AcademicLevel.SSC, AcademicLevel.ALIM),
    (AcademicLevel.DAKHIL, AcademicLevel.ALIM),
    (AcademicLevel.SSC, AcademicLevel.DIPLOMA),
)

# Certificates whose date of birth must match the passport (ACAD-04).
DOB_LEVELS = (AcademicLevel.SSC, AcademicLevel.DAKHIL)

AcademicDoc = AcademicCertificate | AcademicTranscript


def check_academic(ctx: EvaluationContext) -> list[RuleResult]:
    apostilles = ctx.case.of_kind(EApostille)
    certificates = ctx.case.of_kind(AcademicCertificate)
    transcripts = ctx.case.of_kind(AcademicTranscript)
    results: list[RuleResult] = [_acad_01_qr(a) for a in apostilles]
    results += _acad_02_pairs(apostilles, certificates, transcripts, ctx)
    results.append(_acad_03_equivalency([*certificates, *transcripts], ctx))
    results += [_acad_04_identity(d, ctx) for d in (*certificates, *transcripts)]
    results += [_acad_05_notary(d, ctx) for d in (*certificates, *transcripts)]
    return results


# --- helpers ----------------------------------------------------------------------


def _label(doc: AcademicDoc | EApostille) -> str:
    if isinstance(doc, AcademicCertificate):
        return f"Certificate {doc.doc_id}"
    if isinstance(doc, AcademicTranscript):
        return f"Transcript {doc.doc_id}"
    return f"e-Apostille {doc.doc_id}"


def _first_page(doc) -> int | None:
    return min(doc.pages) if doc.pages else None


def _level(doc: AcademicDoc, ctx: EvaluationContext) -> AcademicLevel | None:
    """The document's level when read reliably, else None."""
    return doc.level.value if doc.level.is_reliable(ctx.threshold) else None


def _level_problem(doc: AcademicDoc, ctx: EvaluationContext) -> str | None:
    """Why the level can't be used for pairing, or None when it can."""
    level = doc.level
    if not level.found:
        return "academic level not found"
    if not level.is_reliable(ctx.threshold):
        return f"academic level '{level.value.value}' read with low OCR confidence ({level.confidence:.2f})"
    if level.value is AcademicLevel.OTHER:
        return "academic level is not one the rulebook knows (OTHER)"
    return None


def _join(levels) -> str:
    return ", ".join(level.value for level in levels) or "none"


# --- ACAD-01 e-Apostille QR -------------------------------------------------------


def _acad_01_qr(apostille: EApostille) -> RuleResult:
    page = _first_page(apostille)
    label = _label(apostille)
    evidence: list[Evidence] = [
        ev(apostille.doc_id, "qr_url", Extracted[str](value=apostille.qr_url, confidence=1.0, source_page=page))
    ]
    if apostille.online is not None:
        evidence.append(
            Evidence(doc_id=apostille.doc_id, field="online.status", value=apostille.online.status.value, page=page)
        )

    def result(outcome: Outcome, reason: str) -> RuleResult:
        return RuleResult(rule_id=ACAD_01, outcome=outcome, reason=f"{label}: {reason}", evidence=tuple(evidence))

    url = (apostille.qr_url or "").strip()
    if not apostille.qr_decoded or not url:
        return result(Outcome.FLAG, "QR could not be decoded")
    if not _is_official(url):
        return result(Outcome.FAIL, f"QR does not point to the official e-Apostille site: {url}")

    online = apostille.online
    status = online.status if online is not None else OnlineStatus.NOT_RUN
    detail = online.detail.strip() if online is not None else ""
    if status is OnlineStatus.NOT_RUN:
        return result(Outcome.FLAG, f"QR points to the official site but was not verified online: online checks not enabled ({url})")
    if status is OnlineStatus.UNAVAILABLE:
        return result(Outcome.FLAG, f"online check failed: {detail or 'site or internet unavailable'} ({url})")
    if status is OnlineStatus.NOT_FOUND:
        extra = f" ({detail})" if detail else ""
        return result(Outcome.FAIL, f"official e-Apostille site has no such apostille: {url}{extra}")
    extra = f": {detail}" if detail else ""
    return result(Outcome.PASS, f"verified on the official e-Apostille site{extra} ({url})")


def _is_official(url: str) -> bool:
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").rstrip(".")
    except ValueError:  # malformed URL, e.g. a broken IPv6 literal
        return False
    return parsed.scheme.lower() == "https" and host in OFFICIAL_APOSTILLE_HOSTS


# --- ACAD-02 Mandatory pairs ------------------------------------------------------


def _acad_02_pairs(
    apostilles: list[EApostille],
    certificates: list[AcademicCertificate],
    transcripts: list[AcademicTranscript],
    ctx: EvaluationContext,
) -> list[RuleResult]:
    if not (apostilles or certificates or transcripts):
        return [RuleResult(rule_id=ACAD_02, outcome=Outcome.FLAG, reason="No academic documents found")]

    results: list[RuleResult] = []

    # Documents whose level can't be used for pairing. They are kept (split by kind) so a
    # level left without a partner is FLAGged, not FAILed, while one of them may be it.
    by_level: dict[AcademicLevel, tuple[list[AcademicCertificate], list[AcademicTranscript]]] = {}
    unpaired_certs: list[AcademicCertificate] = []
    unpaired_trans: list[AcademicTranscript] = []
    for doc in (*certificates, *transcripts):
        problem = _level_problem(doc, ctx)
        if problem:
            if isinstance(doc, AcademicCertificate):
                unpaired_certs.append(doc)
            else:
                unpaired_trans.append(doc)
            results.append(
                RuleResult(
                    rule_id=ACAD_02,
                    outcome=Outcome.FLAG,
                    reason=f"{_label(doc)}: {problem}, so it can't be paired with a "
                    f"{'transcript' if isinstance(doc, AcademicCertificate) else 'certificate'}",
                    evidence=(ev(doc.doc_id, "level", doc.level),),
                )
            )
            continue
        certs, trans = by_level.setdefault(doc.level.value, ([], []))
        (certs if isinstance(doc, AcademicCertificate) else trans).append(doc)

    # One result per level, in the rulebook's level order.
    for level in AcademicLevel:
        if level not in by_level:
            continue
        certs, trans = by_level[level]
        evidence = tuple(ev(d.doc_id, "level", d.level) for d in (*certs, *trans))
        cert_ids = ", ".join(d.doc_id for d in certs)
        trans_ids = ", ".join(d.doc_id for d in trans)
        if certs and trans:
            outcome, reason = (
                Outcome.PASS,
                f"{level.value} certificate ({cert_ids}) and transcript ({trans_ids}) both present",
            )
        elif certs and unpaired_trans:
            other_ids = ", ".join(d.doc_id for d in unpaired_trans)
            evidence += tuple(ev(d.doc_id, "level", d.level) for d in unpaired_trans)
            outcome, reason = (
                Outcome.FLAG,
                f"{level.value} certificate has no transcript with a readable level (certificate {cert_ids}); "
                f"transcript(s) {other_ids} have an unreadable level and may be its partner",
            )
        elif certs:
            outcome, reason = Outcome.FAIL, f"{level.value} certificate has no transcript (certificate {cert_ids})"
        elif unpaired_certs:
            other_ids = ", ".join(d.doc_id for d in unpaired_certs)
            evidence += tuple(ev(d.doc_id, "level", d.level) for d in unpaired_certs)
            outcome, reason = (
                Outcome.FLAG,
                f"{level.value} transcript has no certificate with a readable level (transcript {trans_ids}); "
                f"certificate(s) {other_ids} have an unreadable level and may be its partner",
            )
        else:
            outcome, reason = Outcome.FAIL, f"{level.value} transcript has no certificate (transcript {trans_ids})"
        results.append(RuleResult(rule_id=ACAD_02, outcome=outcome, reason=reason, evidence=evidence))

    # Each e-Apostille must be followed by a certificate or transcript.
    paged = sorted(
        (d for d in ctx.case.documents if d.pages),
        key=lambda d: (min(d.pages), d.doc_id),
    )
    for apostille in apostilles:
        evidence = (
            ev(
                apostille.doc_id,
                "pages",
                Extracted[str](
                    value=",".join(map(str, apostille.pages)) or None,
                    confidence=1.0,
                    source_page=_first_page(apostille),
                ),
            ),
        )
        if not apostille.pages:
            results.append(
                RuleResult(
                    rule_id=ACAD_02,
                    outcome=Outcome.FLAG,
                    reason=f"e-Apostille {apostille.doc_id} has no page number, so the document after it is unknown",
                    evidence=evidence,
                )
            )
            continue
        last = max(apostille.pages)
        following = next((d for d in paged if d is not apostille and min(d.pages) > last), None)
        if isinstance(following, (AcademicCertificate, AcademicTranscript)):
            continue
        after = "it is the last document" if following is None else f"next is {following.kind} {following.doc_id}"
        results.append(
            RuleResult(
                rule_id=ACAD_02,
                outcome=Outcome.FLAG,
                reason=f"e-Apostille {apostille.doc_id} is not followed by a certificate or transcript ({after})",
                evidence=evidence,
            )
        )
    return results


# --- ACAD-03 Equivalency ----------------------------------------------------------


def _acad_03_equivalency(docs: list[AcademicDoc], ctx: EvaluationContext) -> RuleResult:
    evidence = tuple(ev(d.doc_id, "level", d.level) for d in docs)
    if not docs:
        return RuleResult(rule_id=ACAD_03, outcome=Outcome.FLAG, reason="No academic documents found")
    found = {lvl for d in docs if (lvl := _level(d, ctx)) is not None}
    levels = [lvl for lvl in AcademicLevel if lvl in found]
    unreadable = [d.doc_id for d in docs if _level(d, ctx) is None]
    unreadable_note = f"; level unreadable on {', '.join(unreadable)}" if unreadable else ""

    track = next((t for t in VALID_TRACKS if all(lvl in found for lvl in t)), None)
    if track is not None:
        name = " + ".join(lvl.value for lvl in track)
        return RuleResult(
            rule_id=ACAD_03,
            outcome=Outcome.PASS,
            reason=f"Valid track {name} (levels found: {_join(levels)}){unreadable_note}",
            evidence=evidence,
        )
    return RuleResult(
        rule_id=ACAD_03,
        outcome=Outcome.FLAG,
        reason=(
            f"No valid track (SSC + HSC, SSC + Alim, Dakhil + Alim, SSC + Diploma) among the levels found: "
            f"{_join(levels)}{unreadable_note}; needs manual review"
        ),
        evidence=evidence,
    )


# --- ACAD-04 Name / DOB -----------------------------------------------------------


def _acad_04_identity(doc: AcademicDoc, ctx: EvaluationContext) -> RuleResult:
    evidence: list[Evidence] = [ev(doc.doc_id, "student_name", doc.student_name)]
    cmp = compare_name(doc.student_name, Person.STUDENT, ctx)
    name_ok = cmp.kind in (MatchKind.EXACT, MatchKind.AFFIDAVIT)
    outcomes = [Outcome.PASS if name_ok else Outcome.FLAG]
    reasons = [f"name: {cmp.reason}"]

    if isinstance(doc, AcademicCertificate):
        dob_outcome, dob_reason, dob_evidence = _dob_check(doc, ctx)
        if dob_outcome is not None:
            outcomes.append(dob_outcome)
            reasons.append(dob_reason)
            evidence += dob_evidence

    level = _level(doc, ctx)
    level_text = f" ({level.value})" if level is not None else ""
    return RuleResult(
        rule_id=ACAD_04,
        outcome=worst(outcomes),
        reason=f"{_label(doc)}{level_text}: " + "; ".join(reasons),
        evidence=tuple(evidence),
    )


def _dob_check(
    cert: AcademicCertificate, ctx: EvaluationContext
) -> tuple[Outcome | None, str, list[Evidence]]:
    """(None, ...) when the certificate's level needs no DOB check."""
    level = _level(cert, ctx)
    level_known = level is not None
    if level_known and level not in DOB_LEVELS:
        return None, "", []

    dob = cert.date_of_birth
    evidence = [ev(cert.doc_id, "date_of_birth", dob)]
    passports = [p for p in ctx.case.of_kind(Passport) if p.date_of_birth.found]
    evidence += [ev(p.doc_id, "date_of_birth", p.date_of_birth) for p in passports]
    reliable = [p for p in passports if p.date_of_birth.is_reliable(ctx.threshold)]
    passport_dobs: set[date] = {p.date_of_birth.value for p in reliable}
    unknown_level = "" if level_known else " (certificate level unreadable, so the DOB check may apply)"

    if not dob.found:
        return Outcome.FLAG, f"date of birth not found on the certificate{unknown_level}", evidence
    if not dob.is_reliable(ctx.threshold):
        return (
            Outcome.FLAG,
            f"date of birth {dob.value:%d-%m-%Y} read with low OCR confidence ({dob.confidence:.2f}){unknown_level}",
            evidence,
        )
    if not passport_dobs:
        why = "read with low OCR confidence" if passports else "not available"
        return (
            Outcome.FLAG,
            f"date of birth {dob.value:%d-%m-%Y} can't be checked: passport date of birth {why}{unknown_level}",
            evidence,
        )
    if len(passport_dobs) > 1:
        shown = ", ".join(f"{d:%d-%m-%Y}" for d in sorted(passport_dobs))
        return Outcome.FLAG, f"passports disagree on the date of birth ({shown}){unknown_level}", evidence
    passport_dob = next(iter(passport_dobs))
    passport_ids = ", ".join(p.doc_id for p in reliable)
    if dob.value == passport_dob:
        return (
            Outcome.PASS,
            f"date of birth {dob.value:%d-%m-%Y} matches passport {passport_ids}",
            evidence,
        )
    return (
        Outcome.FLAG,
        f"date of birth {dob.value:%d-%m-%Y} does not match passport {passport_ids} "
        f"({passport_dob:%d-%m-%Y}){unknown_level}",
        evidence,
    )


def _acad_05_notary(doc: AcademicDoc, ctx: EvaluationContext) -> RuleResult:
    r = notary_rule(ACAD_05, doc.doc_id, doc.notary, ctx)
    return r.model_copy(update={"reason": f"{_label(doc)}: {r.reason}"})

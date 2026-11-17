"""Section 4.8 Academic certificate rules (ACAD-01 .. ACAD-04). All data fictional."""

from datetime import date, timedelta

import pytest

from builders import (
    APOSTILLE_URL,
    HIGH,
    LOW,
    STUDENT,
    STUDENT_DOB,
    academic_certificate,
    academic_set,
    academic_transcript,
    affidavit,
    apostille,
    birth_certificate,
    by_rule,
    ex,
    context,
    notarised,
    passport,
    register_copy,
    trade,
    FATHER,
)

from hklv_rules.models import (
    AcademicCertificate,
    AcademicLevel,
    AcademicTranscript,
    EApostille,
    Extracted,
    OnlineCheck,
    OnlineStatus,
    Outcome,
    Person,
)
from hklv_rules.rules.academic import OFFICIAL_APOSTILLE_HOSTS, check_academic

SSC, HSC, DAKHIL, ALIM, DIPLOMA, BACHELOR, OTHER = (
    AcademicLevel.SSC,
    AcademicLevel.HSC,
    AcademicLevel.DAKHIL,
    AcademicLevel.ALIM,
    AcademicLevel.DIPLOMA,
    AcademicLevel.BACHELOR,
    AcademicLevel.OTHER,
)


# --- local helpers ----------------------------------------------------------------


def results(*docs, **kw):
    return check_academic(context(*docs, **kw))


def of(rule_id, res):
    return [r for r in res if r.rule_id == rule_id]


def one(rule_id, res):
    found = of(rule_id, res)
    assert len(found) == 1, found
    return found[0]


def cert(
    level=SSC,
    level_confidence=HIGH,
    name=STUDENT,
    name_confidence=HIGH,
    dob=STUDENT_DOB,
    dob_confidence=HIGH,
    page=21,
    doc_id="cert-x",
):
    """Certificate with independent confidences per field (the builder shares one)."""
    return AcademicCertificate(
        doc_id=doc_id,
        pages=(page,),
        level=Extracted(value=level, confidence=level_confidence, source_page=page) if level else Extracted(),
        student_name=Extracted(value=name, confidence=name_confidence, source_page=page) if name else Extracted(),
        date_of_birth=Extracted(value=dob, confidence=dob_confidence, source_page=page) if dob else Extracted(),
        notary=notarised(),
    )


def transcript(level=SSC, level_confidence=HIGH, page=23, doc_id="transcript-x"):
    return AcademicTranscript(
        doc_id=doc_id,
        pages=(page,),
        level=Extracted(value=level, confidence=level_confidence, source_page=page) if level else Extracted(),
        student_name=Extracted(value=STUDENT, confidence=HIGH, source_page=page),
        notary=notarised(),
    )


def acad01(*apostilles):
    """ACAD-01 result for one apostille followed by a certificate (keeps ACAD-02 quiet)."""
    return one("ACAD-01", results(*apostilles, academic_certificate(page=21), academic_transcript(page=23)))


# --- full valid set -----------------------------------------------------------------


def test_valid_ssc_hsc_set_passes_everything():
    res = results(*academic_set())
    assert {r.outcome for r in res} == {Outcome.PASS}
    assert len(of("ACAD-01", res)) == 4
    assert len(of("ACAD-02", res)) == 2  # one per level, no apostille problems
    assert len(of("ACAD-03", res)) == 1
    assert len(of("ACAD-04", res)) == 4
    assert len(of("ACAD-05", res)) == 4  # every certificate and transcript


# --- ACAD-01 e-Apostille QR ---------------------------------------------------------


def test_verified_official_qr_passes_with_evidence():
    r = acad01(apostille(doc_id="apostille-20"))
    assert r.outcome is Outcome.PASS
    assert "apostille-20" in r.reason
    fields = {e.field: e for e in r.evidence}
    assert fields["qr_url"].value == APOSTILLE_URL
    assert fields["qr_url"].page == 20
    assert fields["online.status"].value == "VERIFIED"


def test_official_host_constant():
    assert OFFICIAL_APOSTILLE_HOSTS == ("apostille.mygov.bd",)


def test_undecoded_qr_flags():
    r = acad01(apostille(url=None))
    assert r.outcome is Outcome.FLAG
    assert "QR could not be decoded" in r.reason


def test_qr_not_decoded_flag_overrides_stale_url():
    a = EApostille(doc_id="apostille-20", pages=(20,), qr_decoded=False, qr_url=APOSTILLE_URL)
    assert acad01(a).outcome is Outcome.FLAG


def test_blank_url_flags():
    a = EApostille(doc_id="apostille-20", pages=(20,), qr_decoded=True, qr_url="   ")
    assert acad01(a).outcome is Outcome.FLAG


def test_non_https_official_url_fails():
    url = "http://apostille.mygov.bd/application-details/100000000001"
    r = acad01(apostille(url=url))
    assert r.outcome is Outcome.FAIL
    assert "official e-Apostille site" in r.reason and url in r.reason


def test_unofficial_hosts_fail():
    for url in (
        "https://example.org/apostille/100000000001",
        "https://apostille.mygov.bd.example.org/x",  # look-alike suffix
        "https://apostille.mygov.bd@example.org/x",  # userinfo trick
        "https://fake-apostille.mygov.bd/x",
        "apostille.mygov.bd/application-details/1",  # no scheme
        "https://[not-an-ip/x",  # malformed
    ):
        assert acad01(apostille(url=url)).outcome is Outcome.FAIL, url


def test_host_match_ignores_case_port_and_trailing_dot():
    for url in (
        "HTTPS://APOSTILLE.MYGOV.BD/application-details/1",
        "https://apostille.mygov.bd:443/application-details/1",
        "https://apostille.mygov.bd./application-details/1",
    ):
        assert acad01(apostille(url=url)).outcome is Outcome.PASS, url


def test_online_check_not_enabled_flags():
    for status in (None, OnlineStatus.NOT_RUN):
        r = acad01(apostille(online=status))
        assert r.outcome is Outcome.FLAG
        assert "online checks not enabled" in r.reason


def test_online_check_unavailable_flags_with_detail():
    a = EApostille(
        doc_id="apostille-20",
        pages=(20,),
        qr_decoded=True,
        qr_url=APOSTILLE_URL,
        online=OnlineCheck(status=OnlineStatus.UNAVAILABLE, detail="connection timed out"),
    )
    r = acad01(a)
    assert r.outcome is Outcome.FLAG
    assert "online check failed: connection timed out" in r.reason


def test_online_check_unavailable_without_detail_flags():
    assert acad01(apostille(online=OnlineStatus.UNAVAILABLE)).outcome is Outcome.FLAG


def test_site_has_no_such_apostille_fails():
    r = acad01(apostille(online=OnlineStatus.NOT_FOUND))
    assert r.outcome is Outcome.FAIL
    assert "no such apostille" in r.reason


def test_unofficial_url_fails_even_if_online_says_verified():
    assert acad01(apostille(url="https://example.org/x", online=OnlineStatus.VERIFIED)).outcome is Outcome.FAIL


def test_one_acad01_result_per_apostille():
    res = results(*academic_set(levels=(SSC, HSC, BACHELOR)))
    assert len(of("ACAD-01", res)) == 6


# --- ACAD-02 Mandatory pairs ---------------------------------------------------------


def test_pairs_pass_per_level():
    res = of("ACAD-02", results(*academic_set()))
    assert [r.outcome for r in res] == [Outcome.PASS, Outcome.PASS]
    assert res[0].reason.startswith("SSC") and res[1].reason.startswith("HSC")
    assert {e.doc_id for e in res[0].evidence} == {"cert-ssc", "transcript-ssc"}


def test_certificate_without_transcript_fails():
    docs = [apostille(page=20), academic_certificate(SSC, page=21)]
    r = one("ACAD-02", results(*docs))
    assert r.outcome is Outcome.FAIL
    assert "SSC certificate has no transcript" in r.reason and "cert-ssc" in r.reason


def test_transcript_without_certificate_fails():
    docs = [apostille(page=20), academic_transcript(HSC, page=21)]
    r = one("ACAD-02", results(*docs))
    assert r.outcome is Outcome.FAIL
    assert "HSC transcript has no certificate" in r.reason


def test_missing_hsc_transcript_fails_but_ssc_passes():
    docs = academic_set(levels=(SSC,)) + [apostille(doc_id="apostille-24", page=24), academic_certificate(HSC, page=25, dob=None)]
    outcomes = {r.reason.split()[0]: r.outcome for r in of("ACAD-02", results(*docs))}
    assert outcomes == {"SSC": Outcome.PASS, "HSC": Outcome.FAIL}


def test_unreliable_missing_or_other_level_flags_that_document():
    for c in (
        cert(level=SSC, level_confidence=LOW),
        cert(level=None),
        cert(level=OTHER),
    ):
        docs = [apostille(page=20), c]
        r = one("ACAD-02", results(*docs))
        assert r.outcome is Outcome.FLAG, c.level
        assert "cert-x" in r.reason
        assert r.evidence[0].field == "level"


def test_unreliable_level_transcript_flags_and_does_not_fail_its_certificate():
    # Regression (fix 5/9): the SSC transcript exists but its level was read at 0.5, so the
    # SSC certificate must not FAIL with "no transcript"; it FLAGs, naming the transcript.
    docs = [apostille(page=20), cert(level=SSC), apostille(doc_id="apostille-22", page=22), transcript(SSC, 0.5)]
    res = of("ACAD-02", results(*docs))
    assert [r.outcome for r in res] == [Outcome.FLAG, Outcome.FLAG]
    level_flag = next(r for r in res if r.reason.startswith("SSC"))
    assert "SSC certificate has no transcript with a readable level" in level_flag.reason
    assert "cert-x" in level_flag.reason and "transcript-x" in level_flag.reason
    assert {e.doc_id for e in level_flag.evidence} == {"cert-x", "transcript-x"}


def test_unreliable_level_certificate_flags_and_does_not_fail_its_transcript():
    docs = [apostille(page=20), cert(level=None), apostille(doc_id="apostille-22", page=22), transcript(HSC)]
    res = of("ACAD-02", results(*docs))
    assert [r.outcome for r in res] == [Outcome.FLAG, Outcome.FLAG]
    level_flag = next(r for r in res if r.reason.startswith("HSC"))
    assert "HSC transcript has no certificate with a readable level" in level_flag.reason
    assert "cert-x" in level_flag.reason


def test_certificate_alone_still_fails_when_no_document_has_a_level_problem():
    docs = [apostille(page=20), cert(level=SSC)]
    r = one("ACAD-02", results(*docs))
    assert r.outcome is Outcome.FAIL
    assert "SSC certificate has no transcript (certificate cert-x)" in r.reason


def test_unpairable_certificate_does_not_excuse_a_certificate_without_transcript():
    # Only an unpairable TRANSCRIPT can be the missing partner of a certificate.
    docs = [apostille(page=20), cert(level=SSC), apostille(doc_id="apostille-22", page=22), cert(level=OTHER, page=23, doc_id="cert-y")]
    res = of("ACAD-02", results(*docs))
    assert sorted(r.outcome.value for r in res) == ["FAIL", "FLAG"]


def test_apostille_that_is_last_flags():
    docs = academic_set(levels=(SSC,)) + [apostille(doc_id="apostille-99", page=99)]
    flags = [r for r in of("ACAD-02", results(*docs)) if r.outcome is Outcome.FLAG]
    assert len(flags) == 1
    assert "apostille-99 is not followed by a certificate or transcript" in flags[0].reason
    assert "last document" in flags[0].reason


def test_apostille_followed_by_another_apostille_flags():
    docs = [apostille(doc_id="apostille-19", page=19)] + academic_set(levels=(SSC,))
    flags = [r for r in of("ACAD-02", results(*docs)) if r.outcome is Outcome.FLAG]
    assert len(flags) == 1 and "apostille-19" in flags[0].reason


def test_apostille_followed_by_non_academic_document_flags():
    t = trade(FATHER).model_copy(update={"pages": (21,)})
    docs = [apostille(page=20), t, academic_certificate(page=22), academic_transcript(page=23)]
    flags = [r for r in of("ACAD-02", results(*docs)) if r.outcome is Outcome.FLAG]
    assert len(flags) == 1 and "trade_license trade" in flags[0].reason


def test_apostille_without_page_number_flags():
    a = EApostille(doc_id="apostille-x", qr_decoded=True, qr_url=APOSTILLE_URL)
    docs = [a, academic_certificate(page=21), academic_transcript(page=23)]
    flags = [r for r in of("ACAD-02", results(*docs)) if r.outcome is Outcome.FLAG]
    assert len(flags) == 1 and "no page number" in flags[0].reason


def test_multi_page_apostille_followed_by_certificate_is_fine():
    a = EApostille(doc_id="apostille-20", pages=(20, 21), qr_decoded=True, qr_url=APOSTILLE_URL)
    docs = [a, academic_certificate(page=22), apostille(doc_id="apostille-23", page=23), academic_transcript(page=24)]
    assert {r.outcome for r in of("ACAD-02", results(*docs))} == {Outcome.PASS}


def test_no_academic_documents_flags_once():
    r = by_rule(results())
    assert r["ACAD-02"].outcome is Outcome.FLAG
    assert r["ACAD-02"].reason == "No academic documents found"
    assert "ACAD-01" not in r and "ACAD-04" not in r


def test_only_apostille_flags_but_does_not_report_no_documents():
    r = by_rule(results(apostille(page=20)))
    assert r["ACAD-02"].outcome is Outcome.FLAG
    assert "not followed" in r["ACAD-02"].reason


# --- ACAD-03 Equivalency -------------------------------------------------------------


def test_every_valid_track_passes():
    for track in ((SSC, HSC), (SSC, ALIM), (DAKHIL, ALIM), (SSC, DIPLOMA)):
        r = one("ACAD-03", results(*academic_set(levels=track)))
        assert r.outcome is Outcome.PASS, track
        assert " + ".join(l.value for l in track) in r.reason


def test_extra_levels_do_not_spoil_a_valid_track():
    r = one("ACAD-03", results(*academic_set(levels=(SSC, HSC, BACHELOR, AcademicLevel.MASTERS))))
    assert r.outcome is Outcome.PASS


def test_track_counts_levels_from_certificates_and_transcripts_together():
    docs = [apostille(page=20), academic_certificate(SSC, page=21), apostille(doc_id="a-22", page=22), academic_transcript(HSC, page=23)]
    assert one("ACAD-03", results(*docs)).outcome is Outcome.PASS


def test_invalid_combinations_flag():
    for levels in ((HSC,), (DAKHIL, HSC), (SSC,), (BACHELOR,), (DIPLOMA, ALIM)):
        r = one("ACAD-03", results(*academic_set(levels=levels)))
        assert r.outcome is Outcome.FLAG, levels
        assert "No valid track" in r.reason
        for lvl in levels:
            assert lvl.value in r.reason


def test_unreadable_level_is_mentioned_and_does_not_count():
    docs = academic_set(levels=(SSC,)) + [apostille(doc_id="a-24", page=24), cert(level=HSC, level_confidence=LOW, page=25, dob=None)]
    r = one("ACAD-03", results(*docs))
    assert r.outcome is Outcome.FLAG
    assert "level unreadable on cert-x" in r.reason


def test_no_academic_documents_flags_equivalency():
    r = by_rule(results())["ACAD-03"]
    assert r.outcome is Outcome.FLAG and "No academic documents" in r.reason


# --- ACAD-04 Name / DOB --------------------------------------------------------------


def acad04(doc, *extra, **kw):
    res = of("ACAD-04", results(apostille(page=20), doc, *extra, **kw))
    return next(r for r in res if r.evidence[0].doc_id == doc.doc_id)


def test_matching_name_and_dob_pass():
    r = acad04(cert())
    assert r.outcome is Outcome.PASS
    assert "cert-x (SSC)" in r.reason and "15-03-2001 matches passport passport" in r.reason
    fields = {(e.doc_id, e.field) for e in r.evidence}
    assert fields == {("cert-x", "student_name"), ("cert-x", "date_of_birth"), ("passport", "date_of_birth")}


def test_name_mismatch_flags():
    r = acad04(cert(name="TANVIR HASAN"))
    assert r.outcome is Outcome.FLAG
    assert "does not match" in r.reason


def test_name_mismatch_covered_by_affidavit_passes():
    aff = affidavit((Person.STUDENT, STUDENT, "TANVIR AHMAD"))
    assert acad04(cert(name="TANVIR AHMAD"), aff).outcome is Outcome.PASS


def test_low_confidence_or_missing_name_flags():
    assert acad04(cert(name_confidence=LOW)).outcome is Outcome.FLAG
    assert acad04(cert(name=None)).outcome is Outcome.FLAG


def test_dob_mismatch_flags_including_one_day_off():
    for dob in (date(2001, 3, 16), STUDENT_DOB - timedelta(days=1), date(2002, 3, 15)):
        r = acad04(cert(dob=dob))
        assert r.outcome is Outcome.FLAG, dob
        assert "does not match passport" in r.reason


def test_dakhil_certificate_dob_is_checked():
    assert acad04(cert(level=DAKHIL, dob=date(2001, 3, 16))).outcome is Outcome.FLAG
    assert acad04(cert(level=DAKHIL)).outcome is Outcome.PASS


def test_hsc_certificate_dob_is_not_checked():
    r = acad04(cert(level=HSC, dob=date(1999, 1, 1)))
    assert r.outcome is Outcome.PASS
    assert {e.field for e in r.evidence} == {"student_name"}
    assert acad04(cert(level=HSC, dob=None)).outcome is Outcome.PASS


def test_missing_or_low_confidence_certificate_dob_flags():
    assert "not found" in acad04(cert(dob=None)).reason
    assert acad04(cert(dob=None)).outcome is Outcome.FLAG
    r = acad04(cert(dob_confidence=LOW))
    assert r.outcome is Outcome.FLAG and "low OCR confidence" in r.reason


def test_passport_dob_missing_or_unreliable_flags():
    # Replace the default identity docs: passport without DOB / with a low-confidence DOB.
    for p in (passport(dob=None), passport(date_confidence=LOW)):
        r = acad04(cert(), p, birth_certificate(), with_identity_docs=False)
        assert r.outcome is Outcome.FLAG
        assert "passport date of birth" in r.reason


def test_no_passport_flags():
    r = acad04(cert(), with_identity_docs=False)
    assert r.outcome is Outcome.FLAG
    assert "passport date of birth not available" in r.reason


def test_passports_disagreeing_on_dob_flag():
    r = acad04(cert(), passport(dob=date(2001, 3, 16), doc_id="passport-2"))
    assert r.outcome is Outcome.FLAG
    assert "passports disagree" in r.reason


def test_unreadable_level_with_matching_dob_passes():
    r = acad04(cert(level=SSC, level_confidence=LOW))
    assert r.outcome is Outcome.PASS


def test_unreadable_level_with_bad_or_missing_dob_flags():
    for c in (cert(level=None, dob=None), cert(level=SSC, level_confidence=LOW, dob=date(1999, 1, 1))):
        r = acad04(c)
        assert r.outcome is Outcome.FLAG
        assert "level unreadable" in r.reason


def test_name_and_dob_problems_both_reported():
    r = acad04(cert(name="SOMEONE ELSE", dob=date(1999, 1, 1)))
    assert r.outcome is Outcome.FLAG
    assert "name:" in r.reason and "date of birth" in r.reason


def test_transcript_checks_name_only():
    t = academic_transcript(SSC, page=21)
    r = acad04(t)
    assert r.outcome is Outcome.PASS
    assert r.reason.startswith("Transcript transcript-ssc (SSC)")
    assert [e.field for e in r.evidence] == ["student_name"]
    bad = academic_transcript(SSC, page=21, name="SOMEONE ELSE")
    assert acad04(bad).outcome is Outcome.FLAG


def test_one_acad04_result_per_certificate_and_transcript():
    res = results(*academic_set(levels=(SSC, HSC, BACHELOR)))
    assert len(of("ACAD-04", res)) == 6


# --- ACAD-05 notarised (RULES-v2) ---------------------------------------------------


@pytest.mark.parametrize(
    ("notary", "expected"),
    [
        (notarised(), Outcome.PASS),
        (None, Outcome.FAIL),
        (notarised(stamp=False), Outcome.FAIL),
        (notarised(confidence=LOW), Outcome.FLAG),
    ],
)
def test_every_academic_document_must_be_notarised(notary, expected):
    docs = [d.model_copy(update={"notary": notary}) if d.kind == "academic_transcript" else d for d in academic_set()]
    res = of("ACAD-05", results(*docs))
    assert len(res) == 4
    assert {r.outcome for r in res if r.reason.startswith("Transcript")} == {expected}
    assert {r.outcome for r in res if r.reason.startswith("Certificate")} == {Outcome.PASS}


# --- ACAD-01 owner check against the register's copy (RULES-v10) ---------------------


def owner(*register, follows=None, **kw):
    """ACAD-01 for an apostille on page 20 followed by `follows` (an SSC certificate)."""
    doc = follows or academic_certificate(page=21)
    return one("ACAD-01", results(apostille(register=register, **kw), doc, academic_transcript(page=23)))


def test_register_copy_in_the_students_name_passes():
    r = owner(register_copy(title="SSC Certificate (ForAttestation)*"))
    assert r.outcome is Outcome.PASS and "student's name" in r.reason


def test_register_copy_in_another_name_fails():
    r = owner(register_copy("JAHANGIR ALAM", title="SSC Certificate"))
    assert r.outcome is Outcome.FAIL and "JAHANGIR ALAM" in r.reason


def test_register_copy_name_read_with_low_confidence_flags():
    page = register_copy(title="SSC Certificate").model_copy(update={"student_name": ex(STUDENT, LOW)})
    assert owner(page).outcome is Outcome.FLAG


def test_found_but_register_copy_not_read_flags():
    r = owner()  # empty register copy
    assert r.outcome is Outcome.FLAG and "owner was not checked" in r.reason


def test_only_the_register_page_of_the_same_kind_is_compared():
    cert = register_copy(title="SSC Certificate (ForAttestation)*")
    other = register_copy("JAHANGIR ALAM", title="SSC Transcript (ForAttestation)*")
    assert owner(cert, other).outcome is Outcome.PASS


def test_register_holding_another_level_fails():
    hsc = register_copy(title="HSC Certificate", level=ex(AcademicLevel.HSC))
    r = owner(hsc)  # the SSC certificate follows
    assert r.outcome is Outcome.FAIL and "do not include" in r.reason


def test_registration_number_differing_from_the_register_copy_fails():
    page = register_copy(title="SSC Certificate", registration_number=ex("1910534278"))
    cert = academic_certificate(page=21).model_copy(update={"registration_number": ex("1910599999")})
    r = owner(page, follows=cert)
    assert r.outcome is Outcome.FAIL and "registration no." in r.reason


def test_qr_and_printed_number_disagreeing_flags():
    r = owner(register_copy(), printed="999999999999")
    assert r.outcome is Outcome.FLAG and "differs from the printed No." in r.reason


def test_printed_number_unknown_to_the_register_flags_not_fails():
    r = owner(url=None, online=OnlineStatus.NOT_FOUND, printed="100000000001")
    # a misread printed number looks like a fake one, so a person checks it
    assert r.outcome is Outcome.FLAG


def test_register_missing_the_level_flags_when_its_copy_is_incomplete():
    # The SSC page may be among those not downloaded or not read: no FAIL on a page never seen.
    hsc = register_copy(title="HSC Certificate", level=ex(AcademicLevel.HSC))
    a = apostille(register=(hsc,))
    a = a.model_copy(update={"online": a.online.model_copy(update={"register_note": "1 of 2 register pages could not be read"})})
    r = one("ACAD-01", results(a, academic_certificate(page=21), academic_transcript(page=23)))
    assert r.outcome is Outcome.FLAG and "do not include" in r.reason


# --- RULES-v11: a FAIL from the register beats a QR/printed number disagreement ----------


def test_numbers_disagreeing_and_qr_number_unknown_to_the_register_fails():
    r = owner(printed="999999999999", online=OnlineStatus.NOT_FOUND)
    assert r.outcome is Outcome.FAIL and "no such apostille" in r.reason and "differs from the printed No." in r.reason


def test_numbers_disagreeing_and_register_copy_in_another_name_fails():
    r = owner(register_copy("JAHANGIR ALAM", title="SSC Certificate"), printed="999999999999")
    assert r.outcome is Outcome.FAIL and "JAHANGIR ALAM" in r.reason and "differs from the printed No." in r.reason


def test_numbers_disagreeing_and_online_checks_off_still_flags():
    r = owner(printed="999999999999", online=OnlineStatus.NOT_RUN)
    assert r.outcome is Outcome.FLAG and "differs from the printed No." in r.reason

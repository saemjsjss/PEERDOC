"""Seal ring text: notary/advocate wording must start a word. All data fictional."""

import pytest
from reading_builders import make_page

from hklv_extract.common_fields import _seal_says_notary, notary_info
from hklv_ocr.reading import LayoutBlock

NOTARY_SEALS = [
    "NOTARY PULIC",  # misread "PUBLIC", stem survives
    "NOTARYY PUBLIC",
    "N* MD X Notary Public, Dhaka",
    "ADVOCATE MD X",
    "N0TARY PUBLIC",  # O read as zero
]

OTHER_SEALS = [
    "REG NO TAREK TRADERS",  # squashed this was "REGNOTAREK..."
    "SL NO TARIQUL",
    "M/S DONOTARIA",
    "GOVERNMENT OF THE PEOPLE'S REPUBLIC OF BANGLADESH",
    "Chandla Union Parishad",
]


@pytest.mark.parametrize("text", NOTARY_SEALS)
def test_notary_wording_accepted(text):
    assert _seal_says_notary(text)


@pytest.mark.parametrize("text", OTHER_SEALS)
def test_stem_inside_a_word_or_across_words_rejected(text):
    assert not _seal_says_notary(text)


@pytest.mark.parametrize(
    "seal_text,reliable",
    [*((t, True) for t in NOTARY_SEALS), *((t, False) for t in OTHER_SEALS)],
)
def test_notary_info_stamp_follows_the_seal_text(seal_text, reliable):
    # A weakly scored seal (0.82) is confirmed only by notary wording in its own text,
    # even with "Notary Public" printed right next to it.
    base = make_page(["Trade Licence", "Notary Public, Whole of Bangladesh"])
    line = base.lines[-1]
    seal = LayoutBlock(
        label="seal",
        text=seal_text,
        box=(line.box[0], line.box[3] + 20, line.box[0] + 300, line.box[3] + 320),
        score=0.82,
    )
    page = base.model_copy(update={"blocks": (*base.blocks, seal)})
    stamp = notary_info([page]).stamp_present
    assert stamp.value is True
    assert stamp.is_reliable(0.9) is reliable

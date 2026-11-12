"""Red foil seal found by colour (needs OpenCV: runs in the OCR environment)."""

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from hklv_ocr.red_seal import find_red_seals  # noqa: E402

RED = (30, 30, 220)  # BGR


def _page():
    return np.full((1170, 830, 3), 255, np.uint8)


def test_whole_and_half_seal_found():
    page = _page()
    cv2.circle(page, (300, 600), 100, RED, -1)  # whole
    cv2.circle(page, (830, 300), 100, RED, -1)  # half off the right edge
    boxes = sorted(box for box, _ in find_red_seals(page))
    assert len(boxes) == 2


def test_small_logo_red_text_and_red_bar_are_not_seals():
    page = _page()
    cv2.circle(page, (400, 70), 50, RED, -1)  # round logo, too small
    cv2.putText(page, "URGENT", (100, 500), cv2.FONT_HERSHEY_SIMPLEX, 3, RED, 8)
    cv2.rectangle(page, (0, 1000), (829, 1060), RED, -1)  # printed bar
    cv2.circle(page, (400, 800), 100, RED, 6)  # outline rubber stamp
    assert find_red_seals(page) == []


def test_seal_touching_a_red_frame_is_found():
    # a certificate's thick red border joined the seal into one shape that wasn't a disc
    page = _page()
    cv2.rectangle(page, (50, 130), (780, 980), RED, 25)
    cv2.circle(page, (720, 1060), 105, RED, -1)
    assert len(find_red_seals(page)) == 1

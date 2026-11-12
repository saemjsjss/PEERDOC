"""Find a notary's red foil seal: a large, solid red disc, often cut off at the page edge.

The layout model misses it (no ring text, embossed foil), so it is found by colour.
Runs in the OCR environment (OpenCV); returns page-pixel boxes.
"""

from __future__ import annotations

from .reading import Box

MIN_DIAMETER = 0.18  # of the shorter page side; foil seals measure ~0.25, a round red bank logo ~0.15
MIN_FILL = 0.65  # red share of the seal's bounding box: a disc fills 0.785, cut or not (real seals: 0.74-0.81)
MAX_FILL = 0.95  # a solid red rectangle is a printed bar, not a seal
EDGE_PX = 0.01  # within this share of the page side counts as touching the edge


def find_red_seals(bgr) -> list[tuple[Box, float]]:
    """(box, fill) for each red foil seal on a BGR page image."""
    import cv2
    import numpy as np

    h, w = bgr.shape[:2]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    red = (((hue <= 10) | (hue >= 170)) & (sat >= 110) & (val >= 90)).astype(np.uint8)
    # close the embossed texture and the serrated rim into one blob
    k = max(3, int(min(h, w) * 0.01))
    red = cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(red, connectivity=8)
    side, edge = min(h, w), int(min(h, w) * EDGE_PX)
    found = []
    for x, y, bw, bh, area in stats[1:count]:
        long_side, short_side = max(bw, bh), min(bw, bh)
        if long_side < MIN_DIAMETER * side:
            continue
        fill = area / float(bw * bh)
        if not MIN_FILL <= fill <= MAX_FILL:
            continue
        at_edge = x <= edge or y <= edge or x + bw >= w - edge or y + bh >= h - edge
        # whole seal: about square; cut by the page edge: at least a third of it showing
        if short_side / long_side < (0.75 if not at_edge else 0.3):
            continue
        found.append(((int(x), int(y), int(x + bw), int(y + bh)), round(fill, 3)))
    return found

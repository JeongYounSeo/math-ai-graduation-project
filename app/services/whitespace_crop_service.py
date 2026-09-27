"""Conservative, AI-free page proposals based on content and whitespace.

These are proposals, never automatically imported problems. A large gap can
exist inside a problem (notably above a graph), so Gemini and the user review
the resulting boxes before finalization.
"""

from pathlib import Path

import cv2
import numpy as np


def propose_whitespace_crops(page_image_path: Path) -> list[dict]:
    image = cv2.imread(str(page_image_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(page_image_path)
    height, width = image.shape
    # Pale scan lines and paper texture should not create candidate bands.
    ink = image < 175
    margin_x = max(2, round(width * .015))
    ink[:, :margin_x] = False
    ink[:, width - margin_x:] = False
    ink[:max(2, round(height * .008)), :] = False
    ink[height - max(2, round(height * .008)):, :] = False

    # A quiet central gutter distinguishes two-column exam sheets. A line or
    # diagram crossing the centre correctly keeps the page single-column.
    col_density = ink.sum(axis=0)
    window = max(8, round(width * .012))
    search_left, search_right = int(width * .43), int(width * .57)
    gutter_means = np.convolve(col_density, np.ones(window) / window, mode="valid")
    quiet_at = search_left + int(np.argmin(gutter_means[search_left:search_right]))
    center = quiet_at + window // 2
    gutter_density = gutter_means[quiet_at]
    sides = np.r_[col_density[int(width * .12):int(width * .40)],
                  col_density[int(width * .60):int(width * .88)]]
    two_columns = bool(len(sides) and
                       gutter_density < max(2, np.percentile(sides, 65) * .15) and
                       ink[:, margin_x:center].sum() > 100 and
                       ink[:, center:width - margin_x].sum() > 100)
    columns = [(margin_x, center), (center, width - margin_x)] if two_columns else [(margin_x, width - margin_x)]

    results = []
    for left, right in columns:
        region = ink[:, left:right]
        row_counts = region.sum(axis=1)
        min_row_ink = max(4, round((right - left) * .008))
        active = np.flatnonzero(row_counts >= min_row_ink)
        if not len(active):
            continue
        # Only substantial blank bands delimit questions; small gaps between
        # paragraphs, formulae, answer choices, and diagrams remain together.
        split_gap = max(55, round(height * .055))
        split_indices = np.flatnonzero(np.diff(active) > split_gap)
        groups = np.split(active, split_indices + 1)
        for group in groups:
            y1 = max(0, int(group[0]) - 14)
            y2 = min(height, int(group[-1]) + 18)
            if y2 - y1 < max(38, height * .025):
                continue
            # Isolated page numbers / copyright marks near the bottom of a
            # scan are short, detached bands rather than problem content.
            if y1 > height * .82 and y2 - y1 < height * .045:
                continue
            pixels = region[y1:y2]
            if pixels.sum() < max(100, (right - left) * (y2 - y1) * .001):
                continue
            xs = np.flatnonzero(pixels.sum(axis=0) >= 2)
            if not len(xs):
                continue
            x1 = max(0, left + int(xs[0]) - 12)
            x2 = min(width, left + int(xs[-1]) + 16)
            results.append({"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1})
    return sorted(results, key=lambda box: (box["y"], box["x"]))

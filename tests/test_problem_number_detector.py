"""Content-aware crop tests for PDF page images."""
from pathlib import Path

import cv2
import numpy as np


def _create_synthetic_page(path: Path) -> Path:
    image = np.full((1000, 800, 3), 255, dtype=np.uint8)

    # left column: two content blocks
    cv2.rectangle(image, (40, 160), (320, 320), (0, 0, 0), thickness=2)
    cv2.rectangle(image, (40, 420), (320, 620), (0, 0, 0), thickness=2)

    # right column: two content blocks
    cv2.rectangle(image, (440, 160), (720, 320), (0, 0, 0), thickness=2)
    cv2.rectangle(image, (440, 420), (720, 620), (0, 0, 0), thickness=2)

    # bottom blank area
    cv2.rectangle(image, (40, 760), (720, 940), (255, 255, 255), thickness=-1)

    cv2.imwrite(str(path), image)
    return path


def test_crop_service_merges_two_column_layout_into_two_problem_candidates(tmp_path):
    """같은 column 안의 두 content block이 촘촘한 간격(< merge_gap_threshold)으로
    떨어져 있으면 별도 문제로 쪼개지지 않고 하나의 문제 group으로 병합돼야 한다.
    결과적으로 2단 레이아웃에서는 column당 1개씩, 총 2개의 후보만 남는다.
    """
    from app.services.problem_crop_service import crop_problem_candidates

    image_path = _create_synthetic_page(tmp_path / "page.png")
    candidates = crop_problem_candidates(image_path, page_number=1, page=None)

    assert len(candidates) == 2
    assert all(candidate.problem_number is None for candidate in candidates)
    assert all(candidate.crop_box["width"] > 0 for candidate in candidates)
    assert all(candidate.crop_box["height"] > 0 for candidate in candidates)


def test_crop_service_skips_empty_bottom_region(tmp_path):
    from app.services.problem_crop_service import crop_problem_candidates

    image = np.full((1000, 800, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (60, 180), (320, 360), (0, 0, 0), thickness=2)
    image_path = tmp_path / "page_single.png"
    cv2.imwrite(str(image_path), image)

    candidates = crop_problem_candidates(image_path, page_number=1, page=None)

    assert len(candidates) == 1
    assert candidates[0].crop_box["y"] < 400

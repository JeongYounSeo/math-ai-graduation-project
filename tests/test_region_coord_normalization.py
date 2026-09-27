"""region bounding_box 정규화 좌표(0~1) → 픽셀 복원 테스트 (2026-09-17).

버그: Vision 이 이미지 크기와 무관한 좌표를 반환해 세로로 긴 문제에서 region 박스가
상단에 쭈그러들었다. 수정: 프롬프트를 0~1 정규화 좌표로 바꾸고, _parse_bounding_box
가 이미지 크기를 곱해 픽셀로 복원한다. 레거시 픽셀 좌표(>1.0)는 하위호환으로 그대로 둔다.
"""

from app.services.problem_region_extraction_service import ProblemRegionExtractionService

_parse = ProblemRegionExtractionService._parse_bounding_box

W, H = 842, 1954


def test_normalized_coords_scaled_to_pixels():
    r = _parse({"left": 0.0, "top": 0.0, "right": 0.5, "bottom": 0.1}, W, H)
    assert abs(r["right"] - 421.0) < 0.1
    assert abs(r["bottom"] - 195.4) < 0.1
    assert r["left"] == 0.0
    assert r["top"] == 0.0


def test_full_page_normalized():
    r = _parse({"left": 0.0, "top": 0.0, "right": 1.0, "bottom": 1.0}, W, H)
    assert r["right"] == float(W)
    assert r["bottom"] == float(H)


def test_legacy_pixel_coords_preserved():
    """1.0 초과 값이 하나라도 있으면 레거시 픽셀 좌표로 간주하고 그대로 둔다."""
    r = _parse({"left": 40, "top": 30, "right": 760, "bottom": 120}, W, H)
    assert r == {"left": 40.0, "top": 30.0, "right": 760.0, "bottom": 120.0}


def test_no_image_size_passthrough():
    """이미지 크기가 없으면(테스트/폴백) 값을 그대로 통과시킨다."""
    r = _parse({"left": 0.1, "top": 0.1, "right": 0.9, "bottom": 0.9}, None, None)
    assert r["right"] == 0.9


def test_invalid_box_returns_none():
    assert _parse({"left": 0.5, "top": 0.0, "right": 0.5, "bottom": 0.1}, W, H) is None
    assert _parse({"left": 0.0, "top": 0.5, "right": 0.9, "bottom": 0.5}, W, H) is None
    assert _parse("not a dict", W, H) is None
    assert _parse({"left": 0.0}, W, H) is None


def test_mixed_over_one_treated_as_legacy():
    """일부만 1.0 초과여도(예: bottom=1200) 전체를 레거시 픽셀로 취급."""
    r = _parse({"left": 0.0, "top": 0.0, "right": 0.5, "bottom": 1200}, W, H)
    assert r["bottom"] == 1200.0
    assert r["right"] == 0.5

"""세로 구분선이 있어도 trim 이 실제 내용 높이로 축소하는지 검증 (2026-09-26).

버그: 컬럼 구분 세로선이 crop 안에 들어오면 모든 행에 잉크가 잡혀
trim_whitespace_from_crop 이 여백을 못 잘랐다(문제 박스가 다음 문제 전까지 거대).
수정: MIN_INK_WIDTH 이상 잉크가 있는 행만 '내용 행'으로 인정 → 세로선(폭 1~3px) 배제.
"""
import numpy as np
from app.services.problem_block_grouping_service import (
    trim_whitespace_from_crop,
    MIN_INK_WIDTH,
)


def test_vertical_separator_does_not_block_trim():
    page_h, page_w = 2000, 1200
    binary = np.zeros((page_h, page_w), dtype=np.uint8)
    # 실제 내용: 상단에 폭 400px 텍스트 블록(60px 높이)
    binary[400:460, 100:500] = 255
    # 세로 구분선: 컬럼 경계에 폭 2px 로 세로로 길게(내용 아래 여백까지 관통)
    binary[400:1600, 598:600] = 255

    crop = {"x": 0, "y": 380, "width": 600, "height": 1220}
    out = trim_whitespace_from_crop(binary, crop, page_h)
    assert out is not None
    # 세로선을 무시하고 텍스트 블록(60px) + padding 정도로 축소돼야 한다.
    # 최소한 raw(1220) 보다 크게 줄어야 함.
    assert out["height"] < 300, f"trim height too large: {out['height']}"


def test_min_ink_width_constant_reasonable():
    # 세로선(1~3px)은 배제하고 텍스트(수십~수백 px)는 통과할 수준.
    assert 4 <= MIN_INK_WIDTH <= 60


def test_thin_line_only_region_falls_back_or_empty():
    """가는 선만 있는 영역은 폭 임계로 다 걸러지되, 폴백으로 빈 판정(None 가능)."""
    page_h, page_w = 2000, 1200
    binary = np.zeros((page_h, page_w), dtype=np.uint8)
    binary[400:1600, 598:600] = 255  # 세로선만
    crop = {"x": 0, "y": 380, "width": 600, "height": 1220}
    out = trim_whitespace_from_crop(binary, crop, page_h)
    # 폴백(np.any)으로 세로선을 잡아 어떤 box 를 반환하거나 None.
    # 핵심은 예외 없이 처리되는 것.
    assert out is None or out["height"] >= 1

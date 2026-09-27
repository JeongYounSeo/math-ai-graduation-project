"""app.utils.box_geometry 순수 기하 함수 단위 테스트 + PBT.

예시 기반 단위 테스트로 각 함수의 대표 케이스/엣지 케이스를 검증하고,
hypothesis 기반 property test 로 불변식을 검증한다.
각 property 테스트는 ``@settings(max_examples=100)`` 을 갖는다.

정본 설계: DESIGN_overlap_algorithm.md §1, DESIGN_region_coord_validation.md §1
"""

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.utils.box_geometry import (
    area,
    clamp_to_page,
    contains,
    corner_to_xywh,
    intersection,
    iou,
    is_valid_corner,
    overlap_ratio,
    x_overlap,
    xywh_to_corner,
    y_overlap,
)


# ===========================================================================
# 예시 기반 단위 테스트
# ===========================================================================
class TestXywhCornerConversion:
    def test_xywh_to_corner_basic(self):
        assert xywh_to_corner({"x": 10, "y": 20, "width": 30, "height": 40}) == (
            10.0,
            20.0,
            40.0,
            60.0,
        )

    def test_corner_to_xywh_basic(self):
        assert corner_to_xywh(10, 20, 40, 60) == {
            "x": 10.0,
            "y": 20.0,
            "width": 30.0,
            "height": 40.0,
        }

    def test_corner_to_xywh_clamps_negative_size(self):
        # x2 < x1 이면 width 0 으로 보정.
        result = corner_to_xywh(40, 60, 10, 20)
        assert result["width"] == 0.0
        assert result["height"] == 0.0


class TestArea:
    def test_area_tuple(self):
        assert area((0, 0, 10, 5)) == 50.0

    def test_area_dict(self):
        assert area({"x1": 0, "y1": 0, "x2": 10, "y2": 5}) == 50.0

    def test_area_degenerate_is_zero(self):
        assert area((0, 0, 0, 10)) == 0.0

    def test_area_inverted_is_zero(self):
        # x2 < x1, y2 < y1 → 음수 폭은 0 으로 clamp.
        assert area((10, 10, 0, 0)) == 0.0


class TestIntersection:
    def test_intersection_overlap(self):
        assert intersection((0, 0, 10, 10), (5, 5, 15, 15)) == (5, 5, 10, 10)

    def test_intersection_none_when_disjoint(self):
        assert intersection((0, 0, 10, 10), (20, 20, 30, 30)) is None

    def test_intersection_touching_edge_is_none(self):
        # 경계만 맞닿음(면적 0) → None.
        assert intersection((0, 0, 10, 10), (10, 0, 20, 10)) is None


class TestIou:
    def test_iou_identical_is_one(self):
        assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0

    def test_iou_disjoint_is_zero(self):
        assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0

    def test_iou_half_overlap(self):
        # a=100, b=100, inter=50 → union=150 → 50/150.
        a = (0, 0, 10, 10)
        b = (5, 0, 15, 10)
        assert iou(a, b) == pytest.approx(50 / 150)

    def test_iou_degenerate_boxes_zero(self):
        assert iou((0, 0, 0, 0), (0, 0, 0, 0)) == 0.0


class TestOverlapRatio:
    def test_overlap_ratio_contained(self):
        # inner 완전 포함 → inter == area(inner) → ratio 1.0.
        outer = (0, 0, 100, 100)
        inner = (10, 10, 20, 20)
        assert overlap_ratio(outer, inner) == pytest.approx(1.0)

    def test_overlap_ratio_disjoint(self):
        assert overlap_ratio((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0

    def test_overlap_ratio_zero_area(self):
        assert overlap_ratio((0, 0, 0, 10), (0, 0, 10, 10)) == 0.0


class TestContains:
    def test_contains_true(self):
        assert contains((0, 0, 100, 100), (10, 10, 20, 20)) is True

    def test_contains_false(self):
        assert contains((0, 0, 100, 100), (90, 90, 120, 120)) is False

    def test_contains_within_tolerance(self):
        # inner 가 1px 벗어나지만 tol=2 로 포함으로 본다.
        assert contains((0, 0, 100, 100), (-1, -1, 101, 101), tol=2.0) is True

    def test_contains_outside_tolerance(self):
        assert contains((0, 0, 100, 100), (-5, 0, 100, 100), tol=2.0) is False


class TestXYOverlap:
    def test_x_overlap_positive(self):
        assert x_overlap((0, 0, 10, 10), (5, 0, 15, 10)) == 5.0

    def test_x_overlap_disjoint_zero(self):
        assert x_overlap((0, 0, 10, 10), (20, 0, 30, 10)) == 0.0

    def test_y_overlap_positive(self):
        assert y_overlap((0, 0, 10, 10), (0, 5, 10, 15)) == 5.0

    def test_y_overlap_disjoint_zero(self):
        assert y_overlap((0, 0, 10, 10), (0, 20, 10, 30)) == 0.0


class TestClampToPage:
    def test_clamp_within_bounds_unchanged(self):
        assert clamp_to_page((10, 10, 50, 50), 100, 100) == (10, 10, 50, 50)

    def test_clamp_exceeding_bounds(self):
        assert clamp_to_page((-10, -10, 150, 150), 100, 100) == (0, 0, 100, 100)

    def test_clamp_preserves_invariant(self):
        result = clamp_to_page((150, 150, -10, -10), 100, 100)
        x1, y1, x2, y2 = result
        assert x1 <= x2 and y1 <= y2


class TestIsValidCorner:
    def test_valid(self):
        assert is_valid_corner((0, 0, 10, 10)) is True

    def test_valid_negative_allowed(self):
        # 음수 좌표 자체는 허용, 순서 불변식만 검사.
        assert is_valid_corner((-10, -10, 10, 10)) is True

    def test_invalid_x_order(self):
        assert is_valid_corner((10, 0, 0, 10)) is False

    def test_invalid_y_order(self):
        assert is_valid_corner((0, 10, 10, 0)) is False

    def test_invalid_shape(self):
        assert is_valid_corner((0, 0, 10)) is False


# ===========================================================================
# Property-based tests (hypothesis)
# ===========================================================================
# 유효한(순서 불변식 만족) corner box 생성기.
_COORD = st.floats(min_value=-1000, max_value=1000, allow_nan=False, allow_infinity=False)


@st.composite
def valid_corner(draw):
    """x1<=x2, y1<=y2 를 만족하는 corner 튜플."""
    x1 = draw(_COORD)
    x2 = draw(_COORD)
    y1 = draw(_COORD)
    y2 = draw(_COORD)
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    return (x1, y1, x2, y2)


@st.composite
def nondegenerate_corner(draw):
    """면적이 양수인 corner 튜플(x1<x2, y1<y2)."""
    x1 = draw(_COORD)
    y1 = draw(_COORD)
    w = draw(st.floats(min_value=0.5, max_value=1000, allow_nan=False))
    h = draw(st.floats(min_value=0.5, max_value=1000, allow_nan=False))
    return (x1, y1, x1 + w, y1 + h)


@settings(max_examples=100)
@given(a=valid_corner(), b=valid_corner())
def test_property_iou_in_unit_range(a, b):
    """iou(a,b) 는 항상 [0,1]."""
    value = iou(a, b)
    assert 0.0 <= value <= 1.0


@settings(max_examples=100)
@given(a=nondegenerate_corner())
def test_property_iou_self_is_one(a):
    """유효한 non-degenerate box 에 대해 iou(a,a) == 1.0."""
    assert iou(a, a) == pytest.approx(1.0)


@settings(max_examples=100)
@given(a=valid_corner(), b=valid_corner())
def test_property_iou_symmetric(a, b):
    """iou 는 대칭: iou(a,b) == iou(b,a)."""
    assert iou(a, b) == pytest.approx(iou(b, a))


@settings(max_examples=100)
@given(
    box=valid_corner(),
    page_w=st.floats(min_value=1, max_value=2000, allow_nan=False),
    page_h=st.floats(min_value=1, max_value=2000, allow_nan=False),
)
def test_property_clamp_within_page(box, page_w, page_h):
    """clamp_to_page 결과는 항상 페이지 경계 내이며 불변식을 유지한다."""
    x1, y1, x2, y2 = clamp_to_page(box, page_w, page_h)
    assert 0.0 <= x1 <= page_w
    assert 0.0 <= x2 <= page_w
    assert 0.0 <= y1 <= page_h
    assert 0.0 <= y2 <= page_h
    assert x1 <= x2 and y1 <= y2


@settings(max_examples=100)
@given(
    x=_COORD,
    y=_COORD,
    w=st.floats(min_value=0, max_value=2000, allow_nan=False),
    h=st.floats(min_value=0, max_value=2000, allow_nan=False),
)
def test_property_xywh_corner_roundtrip(x, y, w, h):
    """xywh_to_corner -> corner_to_xywh 왕복이 원본과 근사 일치."""
    corner = xywh_to_corner({"x": x, "y": y, "width": w, "height": h})
    back = corner_to_xywh(*corner)
    assert back["x"] == pytest.approx(x)
    assert back["y"] == pytest.approx(y)
    assert back["width"] == pytest.approx(w)
    assert back["height"] == pytest.approx(h)


@settings(max_examples=100)
@given(a=valid_corner(), b=valid_corner())
def test_property_xy_overlap_nonnegative(a, b):
    """x_overlap, y_overlap 는 항상 >= 0."""
    assert x_overlap(a, b) >= 0.0
    assert y_overlap(a, b) >= 0.0

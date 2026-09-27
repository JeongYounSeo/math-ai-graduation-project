"""박스 기하 유틸 (corner 좌표 규약).

좌표 계약 (Single Source of Truth):
- **표준 형식**: corner 방식 ``(x1, y1, x2, y2)`` — 좌상단/우하단.
- **원점**: 이미지 좌상단. 픽셀 단위(float 허용, 정수 픽셀이 기본).
- **불변식(invariant)**: ``x1 <= x2`` 그리고 ``y1 <= y2``.
  (음수 좌표 자체는 이 모듈에서 허용한다. 페이지 경계 clamp 는 ``clamp_to_page`` 로 별도 수행.)

crop 파이프라인의 ``{x, y, width, height}`` (좌상단 + 폭/높이) 규약은
``xywh_to_corner`` 로 corner 로 변환한 뒤 처리하고, 저장 시 ``corner_to_xywh`` 로 역변환한다.

이 모듈은 순수 함수만 제공한다. 외부 의존성/부작용 없음. 표준 라이브러리만 사용한다.
모든 함수는 corner 튜플 ``(x1, y1, x2, y2)`` 또는 corner dict ``{"x1","y1","x2","y2"}``
둘 다 입력으로 받는다(내부 ``_as_corner`` 헬퍼가 정규화).
"""

from __future__ import annotations

CornerTuple = tuple[float, float, float, float]


def _as_corner(box) -> CornerTuple:
    """입력 box 를 corner 튜플 ``(x1, y1, x2, y2)`` 로 정규화한다.

    허용 입력:
    - corner 튜플/리스트: ``(x1, y1, x2, y2)`` (길이 4)
    - corner dict: ``{"x1", "y1", "x2", "y2"}``

    xywh dict(``{"x","y","width","height"}``)는 여기서 직접 받지 않는다.
    필요 시 ``xywh_to_corner`` 로 먼저 변환하라.
    """
    if isinstance(box, dict):
        try:
            return (
                float(box["x1"]),
                float(box["y1"]),
                float(box["x2"]),
                float(box["y2"]),
            )
        except KeyError as exc:  # pragma: no cover - 방어적
            raise ValueError(
                f"corner dict 는 x1,y1,x2,y2 키가 필요합니다: {box!r}"
            ) from exc
    if isinstance(box, (tuple, list)):
        if len(box) != 4:
            raise ValueError(f"corner 튜플은 길이 4여야 합니다: {box!r}")
        return (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
    raise TypeError(f"지원하지 않는 box 타입입니다: {type(box)!r}")


def xywh_to_corner(box: dict) -> CornerTuple:
    """``{"x","y","width","height"}`` -> ``(x1, y1, x2, y2)``.

    (x, y) 는 좌상단, width/height 는 폭/높이. x2 = x + width, y2 = y + height.
    """
    x = float(box["x"])
    y = float(box["y"])
    w = float(box["width"])
    h = float(box["height"])
    return (x, y, x + w, y + h)


def corner_to_xywh(x1: float, y1: float, x2: float, y2: float) -> dict:
    """``(x1, y1, x2, y2)`` -> ``{"x","y","width","height"}``.

    width/height 는 음수가 되지 않도록 0 이상으로 보정한다.
    """
    return {
        "x": float(x1),
        "y": float(y1),
        "width": max(0.0, float(x2) - float(x1)),
        "height": max(0.0, float(y2) - float(y1)),
    }


def area(box) -> float:
    """corner box 의 면적. ``max(0, x2-x1) * max(0, y2-y1)``.

    (x1,y1,x2,y2) 튜플과 {"x1","y1","x2","y2"} dict 둘 다 받는다.
    """
    x1, y1, x2, y2 = _as_corner(box)
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def intersection(a, b) -> CornerTuple | None:
    """두 corner box 의 교차 영역. 교차 없으면 ``None``.

    있으면 교차 corner 튜플 ``(ix1, iy1, ix2, iy2)`` 를 반환한다.
    경계만 맞닿는(면적 0) 경우는 교차 없음으로 본다.
    """
    ax1, ay1, ax2, ay2 = _as_corner(a)
    bx1, by1, bx2, by2 = _as_corner(b)
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return None
    return (ix1, iy1, ix2, iy2)


def iou(a, b) -> float:
    """두 corner box 의 IoU (Intersection over Union). 항상 ``[0, 1]``.

    합집합 면적이 0이면 0.0.
    """
    inter = intersection(a, b)
    if inter is None:
        return 0.0
    inter_area = area(inter)
    union = area(a) + area(b) - inter_area
    if union <= 0:
        return 0.0
    return inter_area / union


def overlap_ratio(a, b) -> float:
    """작은 쪽 기준 겹침 비율. ``inter / min(area(a), area(b))``.

    포함 판정에 유리한 지표. min 면적이 0이면 0.0.
    """
    inter = intersection(a, b)
    if inter is None:
        return 0.0
    m = min(area(a), area(b))
    if m <= 0:
        return 0.0
    return area(inter) / m


def contains(outer, inner, tol: float = 2.0) -> bool:
    """outer 가 inner 를 ``tol`` 오차로 포함하는가."""
    ox1, oy1, ox2, oy2 = _as_corner(outer)
    ix1, iy1, ix2, iy2 = _as_corner(inner)
    return (
        ix1 >= ox1 - tol
        and iy1 >= oy1 - tol
        and ix2 <= ox2 + tol
        and iy2 <= oy2 + tol
    )


def x_overlap(a, b) -> float:
    """가로 겹침 길이. ``max(0, min(a.x2, b.x2) - max(a.x1, b.x1))``. 항상 >= 0."""
    ax1, _, ax2, _ = _as_corner(a)
    bx1, _, bx2, _ = _as_corner(b)
    return max(0.0, min(ax2, bx2) - max(ax1, bx1))


def y_overlap(a, b) -> float:
    """세로 겹침 길이. ``max(0, min(a.y2, b.y2) - max(a.y1, b.y1))``. 항상 >= 0."""
    _, ay1, _, ay2 = _as_corner(a)
    _, by1, _, by2 = _as_corner(b)
    return max(0.0, min(ay2, by2) - max(ay1, by1))


def clamp_to_page(box, page_w: float, page_h: float) -> CornerTuple:
    """페이지 경계 ``[0, page_w] x [0, page_h]`` 로 clamp 한 corner 튜플.

    결과는 항상 페이지 경계 내이며 불변식(x1<=x2, y1<=y2)을 유지한다.
    """
    x1, y1, x2, y2 = _as_corner(box)
    pw = float(page_w)
    ph = float(page_h)

    def _clamp(v: float, lo: float, hi: float) -> float:
        return max(lo, min(v, hi))

    cx1 = _clamp(x1, 0.0, pw)
    cx2 = _clamp(x2, 0.0, pw)
    cy1 = _clamp(y1, 0.0, ph)
    cy2 = _clamp(y2, 0.0, ph)
    # clamp 후에도 순서 불변식을 보장한다.
    if cx2 < cx1:
        cx1, cx2 = cx2, cx1
    if cy2 < cy1:
        cy1, cy2 = cy2, cy1
    return (cx1, cy1, cx2, cy2)


def is_valid_corner(box) -> bool:
    """순서 불변식(``x1 <= x2`` 그리고 ``y1 <= y2``)을 만족하는가.

    음수 좌표 자체는 허용한다(순서 불변식 위주 검사).
    """
    try:
        x1, y1, x2, y2 = _as_corner(box)
    except (TypeError, ValueError):
        return False
    return x1 <= x2 and y1 <= y2

"""영역(region)/crop 후보 겹침 검증 & 보정 (순수 로직).

정본 설계: ``Claude outputs/DESIGN_overlap_algorithm.md`` §1~§9, §9b.

이 모듈은 **순수 로직**만 제공한다. DB 접근/이미지 저장/네트워크 등 외부 부작용이 없다.
기하 계산은 전부 ``app.utils.box_geometry`` 를 재사용한다(기하 함수를 새로 만들지 않는다).

핵심 개념
---------
- 내부 처리용 가변 박스 표현으로 :class:`Region` 경량 dataclass 를 쓴다.
  (corner ``x1,y1,x2,y2`` 를 직접 수정 가능. box_geometry 에 넘길 때는
  ``as_corner()`` 로 ``(x1,y1,x2,y2)`` 튜플로 변환.)
- 관계 분류(:func:`classify_pair`)는 설계 §3 우선순위대로 문자열 상수를 반환한다.
- 해소 전략(§4): shrink / reject / merge_if_contained / clamp_to_parent.
- choice_option 전용 규칙(§5): 세로 정렬·겹침 분할 + index/label 재부여.
- 메인 엔트리(§6): :func:`validate_regions`, :func:`validate_and_resolve`.
- 원문 중간 도형 → question_body N-분할(§9b): :func:`split_question_body_by_separators`.
- fail-open(§7): 보정 중 예외/불변식 위반 → 원본 그대로 반환 + warning 1회.

파이프라인에는 아직 **연결하지 않는다**(미연결). 연결은 이후 단계에서 수행한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from app.utils.box_geometry import (
    area,
    clamp_to_page,
    contains,
    iou,
    is_valid_corner,
    overlap_ratio,
    x_overlap,
    y_overlap,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 임계값 (설계 §2). 모듈 상수 + 함수 인자로 덮어쓰기 가능(테스트 결정성).
# ---------------------------------------------------------------------------
IOU_SIBLING_MAX = 0.15  # 형제 region 허용 IoU 상한
OVERLAP_RATIO_CONTAIN = 0.80  # 작은 쪽의 80%+ 겹치면 '포함'으로 간주
Y_OVERLAP_CHOICE_MAX = 0.20  # choice_option 세로 겹침 허용 비율(높이 대비)
BOUNDARY_TOL = 2.0  # 경계 clamp 허용 오차(px)
MIN_REGION_AREA = 150.0  # 보정 후 이 미만이면 탈락

# 관계 분류 결과 상수 (설계 §3)
CONTAINED = "CONTAINED"
HEAVY = "HEAVY"
TOUCHING = "TOUCHING"
DISJOINT = "DISJOINT"

# 분리자(separator)로 취급하는 비텍스트 region_type (설계 §9b.2)
SEPARATOR_TYPES = frozenset({"figure", "graph", "table", "choice_group"})

# choice_option 라벨 ①②③④⑤ (U+2460 ~ U+2464)
_CIRCLED_DIGITS = ["\u2460", "\u2461", "\u2462", "\u2463", "\u2464"]


# ---------------------------------------------------------------------------
# 데이터 구조
# ---------------------------------------------------------------------------
@dataclass
class Region:
    """내부 처리용 가변 박스 표현.

    corner 좌표를 직접 수정 가능한 경량 표현. box_geometry 에 넘길 때는
    :meth:`as_corner` 로 튜플화한다.
    """

    x1: float
    y1: float
    x2: float
    y2: float
    id: Optional[int] = None
    region_type: Optional[str] = None
    parent_region_id: Optional[int] = None
    order_index: Optional[int] = None
    choice_index: Optional[int] = None
    choice_label: Optional[str] = None
    ocr_text: Optional[str] = None
    text: Optional[str] = None

    def as_corner(self) -> tuple[float, float, float, float]:
        return (float(self.x1), float(self.y1), float(self.x2), float(self.y2))

    @property
    def box_area(self) -> float:
        return area(self.as_corner())


@dataclass
class OverlapReport:
    """관측/디버깅 리포트 (설계 §8)."""

    ok: bool = True
    heavy: list[tuple[int, int, float]] = field(default_factory=list)  # (i, j, iou)
    contained: list[tuple[int, int]] = field(default_factory=list)  # (outer, inner)
    out_of_bounds: list[int] = field(default_factory=list)
    choice_fixed: list[int] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)  # 사람이 읽는 보정 로그


@dataclass
class ResolveResult:
    """보정 결과 (설계 §6)."""

    regions: list
    report: OverlapReport


# ---------------------------------------------------------------------------
# 정규화 헬퍼
# ---------------------------------------------------------------------------
def _to_region(obj) -> Region:
    """다양한 입력을 내부 :class:`Region` 으로 정규화한다.

    허용 입력:
    - :class:`Region` (그대로 복사)
    - corner dict ``{"x1","y1","x2","y2", ...}`` (+ 선택 메타 필드)
    - corner 튜플/리스트 ``(x1,y1,x2,y2)``
    """
    if isinstance(obj, Region):
        return Region(
            x1=obj.x1,
            y1=obj.y1,
            x2=obj.x2,
            y2=obj.y2,
            id=obj.id,
            region_type=obj.region_type,
            parent_region_id=obj.parent_region_id,
            order_index=obj.order_index,
            choice_index=obj.choice_index,
            choice_label=obj.choice_label,
            ocr_text=obj.ocr_text,
            text=obj.text,
        )
    if isinstance(obj, dict):
        return Region(
            x1=float(obj["x1"]),
            y1=float(obj["y1"]),
            x2=float(obj["x2"]),
            y2=float(obj["y2"]),
            id=obj.get("id"),
            region_type=obj.get("region_type"),
            parent_region_id=obj.get("parent_region_id"),
            order_index=obj.get("order_index"),
            choice_index=obj.get("choice_index"),
            choice_label=obj.get("choice_label"),
            ocr_text=obj.get("ocr_text"),
            text=obj.get("text"),
        )
    if isinstance(obj, (tuple, list)):
        if len(obj) != 4:
            raise ValueError(f"corner 튜플은 길이 4여야 합니다: {obj!r}")
        return Region(
            x1=float(obj[0]),
            y1=float(obj[1]),
            x2=float(obj[2]),
            y2=float(obj[3]),
        )
    raise TypeError(f"지원하지 않는 region 타입입니다: {type(obj)!r}")


def _sort_key(r: Region) -> tuple:
    """결정적 정렬 키: (y1, x1, id)."""
    return (r.y1, r.x1, r.id if r.id is not None else 0)


# ---------------------------------------------------------------------------
# 관계 분류 (설계 §3) — 우선순위대로
# ---------------------------------------------------------------------------
def classify_pair(
    a,
    b,
    *,
    iou_threshold: float = IOU_SIBLING_MAX,
    overlap_ratio_contain: float = OVERLAP_RATIO_CONTAIN,
    contain_tol: float = BOUNDARY_TOL,
) -> str:
    """두 형제 box 의 관계를 문자열 상수로 반환한다(설계 §3).

    우선순위:
    1. CONTAINED : overlap_ratio >= overlap_ratio_contain 또는 contains(a,b)/contains(b,a)
    2. HEAVY     : iou >= iou_threshold
    3. TOUCHING  : 0 < iou < iou_threshold
    4. DISJOINT  : iou == 0
    """
    ca = a.as_corner() if isinstance(a, Region) else a
    cb = b.as_corner() if isinstance(b, Region) else b

    if (
        overlap_ratio(ca, cb) >= overlap_ratio_contain
        or contains(ca, cb, tol=contain_tol)
        or contains(cb, ca, tol=contain_tol)
    ):
        return CONTAINED

    value = iou(ca, cb)
    if value >= iou_threshold:
        return HEAVY
    if value > 0.0:
        return TOUCHING
    return DISJOINT


# ---------------------------------------------------------------------------
# 해소 전략 (설계 §4)
# ---------------------------------------------------------------------------
def shrink_pair(a: Region, b: Region, *, min_region_area: float = MIN_REGION_AREA) -> bool:
    """겹치는 두 형제 box 를 덜 겹친 축의 중간선에서 밀어낸다(설계 §4.1).

    세로 겹침 <= 가로 겹침이면 세로 분리, 아니면 가로 분리.
    분할 후 어느 한쪽 area < min_region_area 가 되면 **원상복구**하고
    ``False`` 를 반환한다(reject fallback 신호). 성공 시 ``True``.
    """
    orig = (a.x1, a.y1, a.x2, a.y2, b.x1, b.y1, b.x2, b.y2)
    xo = x_overlap(a.as_corner(), b.as_corner())
    yo = y_overlap(a.as_corner(), b.as_corner())

    if yo <= xo:
        # 세로 겹침이 더 작다 → 세로로 분리(위/아래 문제 경계).
        mid = (max(a.y1, b.y1) + min(a.y2, b.y2)) / 2.0
        top, bot = (a, b) if a.y1 <= b.y1 else (b, a)
        top.y2 = mid
        bot.y1 = mid
    else:
        # 가로 겹침이 더 작다 → 가로로 분리(좌/우 컬럼 침범).
        mid = (max(a.x1, b.x1) + min(a.x2, b.x2)) / 2.0
        left, right = (a, b) if a.x1 <= b.x1 else (b, a)
        left.x2 = mid
        right.x1 = mid

    if a.box_area < min_region_area or b.box_area < min_region_area:
        # 원상복구.
        (a.x1, a.y1, a.x2, a.y2, b.x1, b.y1, b.x2, b.y2) = orig
        return False
    return True


def reject_smaller(a: Region, b: Region) -> Region:
    """HEAVY 겹치는 두 후보 중 area 가 작은 쪽을 반환(탈락 대상, 설계 §4.2).

    ink_ratio 정보가 없으므로 area 기준으로 판정한다. 동률이면 b 를 탈락.
    """
    return a if a.box_area < b.box_area else b


def merge_if_contained(outer: Region, inner: Region) -> None:
    """CONTAINED 관계면 inner 를 outer 의 자식으로 강등한다(설계 §4.3).

    inner.parent_region_id 를 outer.id 로 설정. 좌표는 유지(병합/흡수하지 않고
    부모-자식 관계로 유지).
    """
    inner.parent_region_id = outer.id


def clamp_to_parent(
    child: Region, parent: Region, *, tol: float = BOUNDARY_TOL
) -> bool:
    """자식이 부모 경계를 tol 넘게 벗어나면 부모 안으로 clamp 한다(설계 §4.4).

    보정이 일어났으면 ``True``, 이미 경계 내였으면 ``False`` 를 반환한다.
    """
    if contains(parent.as_corner(), child.as_corner(), tol=tol):
        return False
    px1, py1, px2, py2 = parent.as_corner()
    child.x1 = max(px1, min(child.x1, px2))
    child.x2 = max(px1, min(child.x2, px2))
    child.y1 = max(py1, min(child.y1, py2))
    child.y2 = max(py1, min(child.y2, py2))
    if child.x2 < child.x1:
        child.x1, child.x2 = child.x2, child.x1
    if child.y2 < child.y1:
        child.y1, child.y2 = child.y2, child.y1
    return True


# ---------------------------------------------------------------------------
# choice_option 전용 규칙 (설계 §5)
# ---------------------------------------------------------------------------
def validate_choice_options(
    options,
    *,
    y_overlap_choice_max: float = Y_OVERLAP_CHOICE_MAX,
) -> list[Region]:
    """객관식 보기(choice_option)를 세로 정렬·겹침 분할하고 index/label 재부여(설계 §5).

    - y1 기준 정렬.
    - 인접 쌍의 세로 겹침이 ``y_overlap_choice_max * min(height)`` 초과면 중간선 분할.
    - 재정렬 후 choice_index 1..N, choice_label 은 ①..⑤ (U+2460~U+2464).
      5개 초과분의 label 은 None(정답 여부/의미는 건드리지 않음).

    입력 순서를 파괴하지 않도록 정렬된 **새 리스트**를 반환한다(원 Region 객체는
    가변으로 좌표/메타가 갱신됨).
    """
    opts = sorted((_to_region(o) if not isinstance(o, Region) else o for o in options),
                  key=lambda o: (o.y1, o.x1))

    for prev, cur in zip(opts, opts[1:]):
        h = min(prev.y2 - prev.y1, cur.y2 - cur.y1)
        if h <= 0:
            continue
        if y_overlap(prev.as_corner(), cur.as_corner()) > y_overlap_choice_max * h:
            mid = (prev.y2 + cur.y1) / 2.0
            prev.y2 = mid
            cur.y1 = mid

    # 분할로 y1 이 바뀌었을 수 있으니 재정렬 후 index/label 재부여.
    opts.sort(key=lambda o: (o.y1, o.x1))
    for idx, opt in enumerate(opts):
        opt.choice_index = idx + 1
        opt.choice_label = _CIRCLED_DIGITS[idx] if idx < len(_CIRCLED_DIGITS) else None

    return opts


# ---------------------------------------------------------------------------
# 검증 (보정 없음) — 설계 §6
# ---------------------------------------------------------------------------
def validate_regions(
    regions,
    page_w: float,
    page_h: float,
    *,
    iou_threshold: float = IOU_SIBLING_MAX,
    overlap_ratio_contain: float = OVERLAP_RATIO_CONTAIN,
    contain_tol: float = BOUNDARY_TOL,
) -> OverlapReport:
    """형제 region 들의 겹침/포함/경계이탈을 **검출만** 한다(보정 없음).

    fail-open: 불변식 위반 입력이면 report.ok=False 로 표시하고 warning 1회.
    """
    report = OverlapReport()
    try:
        regs = [_to_region(r) for r in regions]
    except (TypeError, ValueError, KeyError):
        logger.warning("validate_regions: region 정규화 실패 → fail-open", exc_info=False)
        report.ok = False
        report.actions.append("정규화 실패(fail-open)")
        return report

    # 불변식 검사.
    for i, r in enumerate(regs):
        if not is_valid_corner(r.as_corner()):
            report.ok = False
            report.actions.append(f"불변식 위반 region index={i}")

    # 페이지 경계 이탈 검출.
    for i, r in enumerate(regs):
        cl = clamp_to_page(r.as_corner(), page_w, page_h)
        if cl != r.as_corner():
            report.out_of_bounds.append(i)

    # 형제쌍 관계 분류.
    for i in range(len(regs)):
        for j in range(i + 1, len(regs)):
            rel = classify_pair(
                regs[i],
                regs[j],
                iou_threshold=iou_threshold,
                overlap_ratio_contain=overlap_ratio_contain,
                contain_tol=contain_tol,
            )
            if rel == CONTAINED:
                a_area = regs[i].box_area
                b_area = regs[j].box_area
                outer, inner = (i, j) if a_area >= b_area else (j, i)
                report.contained.append((outer, inner))
            elif rel == HEAVY:
                report.heavy.append((i, j, iou(regs[i].as_corner(), regs[j].as_corner())))

    if report.heavy or report.out_of_bounds or not report.ok:
        report.ok = report.ok and not report.heavy
    return report


# ---------------------------------------------------------------------------
# 메인 엔트리: 검증 + 보정 (설계 §6)
# ---------------------------------------------------------------------------
def validate_and_resolve(
    regions,
    page_w: float,
    page_h: float,
    *,
    mode: str = "regions",
    iou_threshold: float = IOU_SIBLING_MAX,
    overlap_ratio_contain: float = OVERLAP_RATIO_CONTAIN,
    y_overlap_choice_max: float = Y_OVERLAP_CHOICE_MAX,
    boundary_tol: float = BOUNDARY_TOL,
    min_region_area: float = MIN_REGION_AREA,
) -> ResolveResult:
    """겹침 검증 + 보정을 수행하고 :class:`ResolveResult` 를 반환한다(설계 §6).

    절차:
    1. corner 정규화 + 페이지 clamp + 불변식 검사. 위반 시 fail-open(원본 반환).
    2. 부모(full_problem) 식별 → 자식 clamp_to_parent.
    3. 형제쌍 분류 → 전략 적용
       - CONTAINED -> merge_if_contained
       - HEAVY     -> mode=="candidates" reject / mode=="regions" shrink(실패 시 reject)
       - TOUCHING  -> report 기록만
    4. choice_option 그룹 -> validate_choice_options
    5. 보정 후 재검증 1회 → 여전히 HEAVY면 report 에 남기고 fail-open.

    mode:
    - "candidates": crop 후보 분리 단계 → reject 위주.
    - "regions": 문제 내부 의미 영역 → shrink/clamp 위주.
    """
    report = OverlapReport()

    # --- 1) 정규화 + 불변식 검사 (fail-open) ---
    try:
        original = list(regions)
        regs = [_to_region(r) for r in regions]
    except (TypeError, ValueError, KeyError):
        logger.warning("validate_and_resolve: region 정규화 실패 → 원본 반환(fail-open)")
        report.ok = False
        report.actions.append("정규화 실패(fail-open)")
        return ResolveResult(regions=list(regions), report=report)

    # 불변식 위반이 하나라도 있으면 보정하지 않고 원본 그대로 반환(fail-open).
    for i, r in enumerate(regs):
        if not is_valid_corner(r.as_corner()):
            logger.warning(
                "validate_and_resolve: 불변식 위반 입력(index=%s) → 원본 반환(fail-open)", i
            )
            report.ok = False
            report.actions.append(f"불변식 위반 index={i} → fail-open")
            return ResolveResult(regions=original, report=report)

    try:
        # 페이지 경계 clamp.
        for i, r in enumerate(regs):
            cl = clamp_to_page(r.as_corner(), page_w, page_h)
            if cl != r.as_corner():
                report.out_of_bounds.append(i)
                r.x1, r.y1, r.x2, r.y2 = cl
                report.actions.append(f"page clamp index={i}")

        # --- 2) 부모(full_problem) 식별 → 자식 clamp_to_parent ---
        parents = [r for r in regs if r.region_type == "full_problem"]
        for parent in parents:
            for child in regs:
                if child is parent:
                    continue
                # 명시적 부모-자식 또는 부모가 하나뿐이면 전부 자식으로 간주.
                is_child = (
                    child.parent_region_id == parent.id and parent.id is not None
                ) or (len(parents) == 1 and child.region_type != "full_problem")
                if is_child and clamp_to_parent(child, parent, tol=boundary_tol):
                    report.actions.append(
                        f"clamp_to_parent child_id={child.id} parent_id={parent.id}"
                    )

        # --- 3) 형제쌍 분류 → 전략 적용 ---
        # full_problem(부모)은 형제 겹침 판정에서 제외(자식을 당연히 감싸므로).
        parent_ids = {id(p) for p in parents}
        siblings = [r for r in regs if id(r) not in parent_ids]
        rejected: set[int] = set()

        for i in range(len(siblings)):
            for j in range(i + 1, len(siblings)):
                if id(siblings[i]) in rejected or id(siblings[j]) in rejected:
                    continue
                a, b = siblings[i], siblings[j]
                rel = classify_pair(
                    a,
                    b,
                    iou_threshold=iou_threshold,
                    overlap_ratio_contain=overlap_ratio_contain,
                    contain_tol=boundary_tol,
                )
                if rel == CONTAINED:
                    outer, inner = (a, b) if a.box_area >= b.box_area else (b, a)
                    merge_if_contained(outer, inner)
                    report.contained.append((regs.index(outer), regs.index(inner)))
                    report.actions.append(
                        f"merge_if_contained outer={outer.id} inner={inner.id}"
                    )
                elif rel == HEAVY:
                    report.heavy.append(
                        (regs.index(a), regs.index(b), iou(a.as_corner(), b.as_corner()))
                    )
                    if mode == "candidates":
                        loser = reject_smaller(a, b)
                        rejected.add(id(loser))
                        report.actions.append(f"reject candidate id={loser.id}")
                    else:  # regions -> shrink, 실패 시 reject fallback
                        ok = shrink_pair(a, b, min_region_area=min_region_area)
                        if ok:
                            report.actions.append(
                                f"shrink pair ({a.id},{b.id})"
                            )
                        else:
                            loser = reject_smaller(a, b)
                            rejected.add(id(loser))
                            report.actions.append(
                                f"shrink 취소 → reject id={loser.id}"
                            )
                # TOUCHING/DISJOINT: 보정 없음.

        # reject 반영.
        if rejected:
            regs = [r for r in regs if id(r) not in rejected]

        # --- 4) choice_option 그룹 보정 ---
        choice_opts = [r for r in regs if r.region_type == "choice_option"]
        if len(choice_opts) >= 2:
            fixed = validate_choice_options(
                choice_opts, y_overlap_choice_max=y_overlap_choice_max
            )
            report.choice_fixed = [c.id for c in fixed if c.id is not None]
            report.actions.append(f"validate_choice_options n={len(fixed)}")

        # --- 5) 재검증 1회 ---
        recheck = validate_regions(
            [r for r in regs if id(r) not in parent_ids],
            page_w,
            page_h,
            iou_threshold=iou_threshold,
            overlap_ratio_contain=overlap_ratio_contain,
            contain_tol=boundary_tol,
        )
        # 재검증에서 발견된 HEAVY 는 report 에 남기고 더 보정하지 않는다(fail-open).
        report.ok = not recheck.heavy
        if recheck.heavy:
            report.actions.append("재검증 후 잔여 HEAVY 존재(fail-open)")

    except Exception:  # noqa: BLE001 — fail-open: 어떤 예외도 밖으로 던지지 않는다.
        logger.warning("validate_and_resolve: 보정 중 예외 → 원본 반환(fail-open)", exc_info=True)
        report.ok = False
        report.actions.append("보정 중 예외(fail-open)")
        return ResolveResult(regions=original, report=report)

    return ResolveResult(regions=regs, report=report)


# ---------------------------------------------------------------------------
# 9b. 원문 중간 도형 → question_body N-분할 (설계 §9b)
# ---------------------------------------------------------------------------
def _union_separator_bands(separators: list[Region]) -> list[tuple[float, float]]:
    """분리자들의 y구간을 모아 겹치면 union 으로 합친 뒤 (y1,y2) 리스트로 반환.

    설계 §9b.2 주의: "분리자끼리 y가 겹치면 union으로 하나의 분리자 밴드로 합친다".
    결정적으로 y1 오름차순 정렬 후 병합한다.
    """
    if not separators:
        return []
    intervals = sorted(((s.y1, s.y2) for s in separators), key=lambda t: (t[0], t[1]))
    merged: list[list[float]] = [list(intervals[0])]
    for lo, hi in intervals[1:]:
        if lo <= merged[-1][1]:  # 겹치거나 맞닿음 → 합친다.
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return [(lo, hi) for lo, hi in merged]


def split_question_body_by_separators(
    full_problem,
    children,
    *,
    boundary_tol: float = BOUNDARY_TOL,
    min_region_area: float = MIN_REGION_AREA,
) -> list[Region]:
    """full_problem 을 끼어든 비텍스트 분리자 기준으로 밴드 분할한다(설계 §9b.2).

    - 비텍스트(figure/graph/table/choice_group)의 y구간을 분리자로 모은다.
    - 분리자끼리 y 가 겹치면 union 으로 합친다.
    - full_problem 세로축을 분리자 기준으로 밴드로 자른다.
    - 분리자가 아닌 밴드 각각을 question_body region 으로 만든다(clamp_to_parent 적용).
    - question_body 0개 → 경고, full_problem 만 유지(빈 리스트 아님, full_problem 반환).
      1개 → 분할 안 함(기존과 동일). 2개 이상 → N-분할.
    - 생성 region 전체(question_body + 분리자)에 order_index 를 위→아래 순으로 부여.

    **Problem row 는 절대 쪼개지 않는다.** 이 함수는 region 만 다룬다.
    반환: order_index 순으로 정렬된 region 리스트(question_body + 분리자 포함).

    TODO(설계 §9b.3): 좌우 감쌈(ㄴ자/ㄷ자) 케이스의 x-2차 분할은 후순위이므로
    이번 단계에서는 구현하지 않는다(세로 밴드 1차 분할만 수행).
    """
    parent = full_problem if isinstance(full_problem, Region) else _to_region(full_problem)
    child_regs = [c if isinstance(c, Region) else _to_region(c) for c in children]

    separators = [c for c in child_regs if c.region_type in SEPARATOR_TYPES]
    sep_bands = _union_separator_bands(separators)

    # 밴드 후보: top..sep1.y1, sep1.y2..sep2.y1, ..., sepN.y2..bottom
    top, bottom = parent.y1, parent.y2
    text_bands: list[tuple[float, float]] = []
    cursor = top
    for lo, hi in sep_bands:
        # 분리자 위쪽 텍스트 밴드.
        if lo > cursor:
            text_bands.append((cursor, lo))
        cursor = max(cursor, hi)
    if bottom > cursor:
        text_bands.append((cursor, bottom))

    # 면적/두께가 사실상 0인 밴드는 제외.
    text_bands = [(lo, hi) for lo, hi in text_bands if hi - lo > 0]

    # question_body region 생성.
    question_bodies: list[Region] = []
    for lo, hi in text_bands:
        qb = Region(
            x1=parent.x1,
            y1=lo,
            x2=parent.x2,
            y2=hi,
            region_type="question_body",
            parent_region_id=parent.id,
        )
        clamp_to_parent(qb, parent, tol=boundary_tol)
        question_bodies.append(qb)

    if not question_bodies:
        logger.warning(
            "split_question_body_by_separators: question_body 밴드 0개 → full_problem만 유지"
        )
        # full_problem 만 유지(분리자는 그대로 순서 부여해 반환).
        result = list(separators)
        result.sort(key=lambda r: (r.y1, r.x1))
        for idx, r in enumerate(result):
            r.order_index = idx
        return result

    # question_body + 분리자를 y 순으로 합쳐 전체 순서(order_index) 부여.
    ordered = question_bodies + separators
    ordered.sort(key=lambda r: (r.y1, r.x1))
    for idx, r in enumerate(ordered):
        r.order_index = idx

    return ordered


def assemble_question_body_text(regions) -> str:
    """question_body region 들을 order_index 순으로 텍스트를 이어붙인다(설계 §9b.4).

    각 region 의 텍스트는 ``ocr_text`` 우선, 없으면 ``text`` 필드를 사용한다.
    order_index 가 없는 region 은 뒤로 밀린다(안정 정렬). 저장은 조각, 조회는 병합.
    """
    regs = [r if isinstance(r, Region) else _to_region(r) for r in regions]
    bodies = [r for r in regs if r.region_type == "question_body"]
    bodies.sort(key=lambda r: (r.order_index if r.order_index is not None else 1_000_000, r.y1))
    parts: list[str] = []
    for r in bodies:
        piece = r.ocr_text if r.ocr_text is not None else r.text
        if piece:
            parts.append(piece)
    return "\n".join(parts)

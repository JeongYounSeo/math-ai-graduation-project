"""region_overlap_validator 순수 로직 단위 테스트 + PBT.

정본 설계: ``Claude outputs/DESIGN_overlap_algorithm.md`` §9(표 1~10), §9b(표 11~15).

각 테스트는 대응하는 설계 표 번호를 주석으로 명시한다. 순수 로직만 대상이며
DB/파일시스템/네트워크를 건드리지 않는다. hypothesis property test 는
``deadline=None`` 으로 Windows 환경 타이밍 영향을 배제한다.

주의: 이 검증기는 아직 crop/region 파이프라인에 **연결되지 않은** 상태다(미연결).
파이프라인 훅 연결은 이후 단계에서 수행한다.
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.utils.box_geometry import contains, x_overlap, y_overlap
from app.services.region_overlap_validator import (
    BOUNDARY_TOL,
    CONTAINED,
    DISJOINT,
    HEAVY,
    TOUCHING,
    OverlapReport,
    Region,
    ResolveResult,
    assemble_question_body_text,
    classify_pair,
    clamp_to_parent,
    shrink_pair,
    split_question_body_by_separators,
    validate_and_resolve,
    validate_choice_options,
    validate_regions,
)

_CIRCLED = ["\u2460", "\u2461", "\u2462", "\u2463", "\u2464"]  # ①②③④⑤


def _r(x1, y1, x2, y2, **kw):
    return Region(x1=x1, y1=y1, x2=x2, y2=y2, **kw)


# ===========================================================================
# §9 표 1 — 두 형제 세로로 조금 겹침(HEAVY, mode="regions") → 중간선 세로 분할
# ===========================================================================
def test_case1_vertical_heavy_shrink_regions():
    # 두 박스 100x100, 세로로 40px 겹침(IoU≥0.15 → HEAVY), 가로는 완전 일치.
    a = _r(0, 0, 100, 100, id=1, region_type="question_body")
    b = _r(0, 60, 100, 160, id=2, region_type="question_body")
    # 겹침이 HEAVY 인지 먼저 확인.
    assert classify_pair(a, b) == HEAVY

    result = validate_and_resolve([a, b], 200, 200, mode="regions")
    ra, rb = result.regions
    # 세로 겹침이 더 작으므로 세로로 분리 → 분할 후 y_overlap ≈ 0.
    assert y_overlap(ra.as_corner(), rb.as_corner()) == pytest.approx(0.0, abs=1e-6)
    assert result.report.ok is True


# ===========================================================================
# §9 표 2 — 두 형제 가로로 컬럼 침범(HEAVY) → 중간선 가로 분할
# ===========================================================================
def test_case2_horizontal_heavy_shrink_regions():
    # 세로로 완전 일치(세로 겹침 큼), 가로로 40px 겹침(IoU≥0.15 → HEAVY).
    a = _r(0, 0, 100, 100, id=1, region_type="question_body")
    b = _r(60, 0, 160, 100, id=2, region_type="question_body")
    assert classify_pair(a, b) == HEAVY

    result = validate_and_resolve([a, b], 200, 200, mode="regions")
    ra, rb = result.regions
    assert x_overlap(ra.as_corner(), rb.as_corner()) == pytest.approx(0.0, abs=1e-6)
    assert result.report.ok is True


# ===========================================================================
# §9 표 3 — inner 가 outer 에 80%+ 포함 → merge_if_contained / parent 설정
# ===========================================================================
def test_case3_contained_sets_parent():
    outer = _r(0, 0, 200, 200, id=10, region_type="condition_box")
    inner = _r(20, 20, 60, 60, id=11, region_type="formula")
    assert classify_pair(outer, inner) == CONTAINED

    result = validate_and_resolve([outer, inner], 300, 300, mode="regions")
    # inner.parent_region_id == outer.id
    inner_after = next(r for r in result.regions if r.id == 11)
    assert inner_after.parent_region_id == 10


# ===========================================================================
# §9 표 4 — 자식이 부모(full_problem) 경계 밖 → clamp_to_parent
# ===========================================================================
def test_case4_child_clamped_to_parent():
    parent = _r(0, 0, 100, 100, id=1, region_type="full_problem")
    # 자식이 오른쪽/아래로 부모 밖으로 크게 삐져나감.
    child = _r(50, 50, 150, 150, id=2, region_type="figure", parent_region_id=1)

    result = validate_and_resolve([parent, child], 300, 300, mode="regions")
    child_after = next(r for r in result.regions if r.id == 2)
    parent_after = next(r for r in result.regions if r.id == 1)
    assert contains(parent_after.as_corner(), child_after.as_corner(), tol=BOUNDARY_TOL)


# ===========================================================================
# §9 표 5 — choice ①②③ 세로 겹침 → 분할 + index/label 재부여(1..N, ①..③)
# ===========================================================================
def test_case5_choice_options_split_and_relabel():
    # 세 보기가 세로로 겹쳐 있음(각 높이 40, 겹침 20).
    o1 = _r(0, 0, 100, 40, id=1, region_type="choice_option")
    o2 = _r(0, 20, 100, 60, id=2, region_type="choice_option")
    o3 = _r(0, 40, 100, 80, id=3, region_type="choice_option")

    fixed = validate_choice_options([o1, o2, o3])
    # index 1..3, label ①②③.
    assert [c.choice_index for c in fixed] == [1, 2, 3]
    assert [c.choice_label for c in fixed] == _CIRCLED[:3]
    # 인접 겹침 해소(허용 비율 이내).
    for prev, cur in zip(fixed, fixed[1:]):
        h = min(prev.y2 - prev.y1, cur.y2 - cur.y1)
        assert y_overlap(prev.as_corner(), cur.as_corner()) <= 0.20 * h + 1e-6


def test_case5b_choice_options_over_five_labels_none():
    # 6개 → 6번째 label 은 None(①~⑤ 우선, 초과분 None).
    opts = [_r(0, i * 50, 100, i * 50 + 40, id=i, region_type="choice_option")
            for i in range(6)]
    fixed = validate_choice_options(opts)
    assert [c.choice_index for c in fixed] == [1, 2, 3, 4, 5, 6]
    assert fixed[5].choice_label is None
    assert fixed[:5] == fixed[:5]  # 앞 5개는 ①~⑤
    assert [c.choice_label for c in fixed[:5]] == _CIRCLED


# ===========================================================================
# §9 표 6 — mode="candidates", 중복 후보 → 작은 쪽 reject(개수 감소)
# ===========================================================================
def test_case6_candidates_reject_smaller():
    # crop 후보 단계: 후보는 full_problem 부모가 아니라 일반 후보(중복 검출).
    big = _r(0, 0, 100, 100, id=1, region_type="question_body")
    # HEAVY 로 겹치되 포함은 아닌 작은 후보(IoU=0.20, overlap_ratio=0.51<0.80).
    small = _r(50, 50, 120, 120, id=2, region_type="question_body")
    assert classify_pair(big, small) == HEAVY

    result = validate_and_resolve([big, small], 300, 300, mode="candidates")
    ids = {r.id for r in result.regions}
    # 작은 쪽(id=2)이 탈락.
    assert 2 not in ids
    assert len(result.regions) == 1


# ===========================================================================
# §9 표 7 — 분할 결과 area<MIN → shrink 취소 → reject fallback
# ===========================================================================
def test_case7_shrink_cancel_falls_back_to_reject():
    # shrink_pair 직접 검증: 분할 후 한쪽 area 가 MIN 미만이면 취소(원상복구).
    a2 = _r(0, 0, 200, 200)
    b2 = _r(0, 199, 200, 200)  # 겹침 1, 분리 후 b 높이 ~0 → area<MIN
    before = (b2.x1, b2.y1, b2.x2, b2.y2)
    ok = shrink_pair(a2, b2, min_region_area=150.0)
    assert ok is False  # 취소됨(원상복구)
    assert (b2.x1, b2.y1, b2.x2, b2.y2) == before  # 좌표 원상복구

    # validate_and_resolve: HEAVY 쌍 + 높은 min_region_area 로 shrink 강제 취소 → reject.
    a = _r(0, 0, 200, 200, id=1, region_type="question_body")
    b = _r(0, 150, 200, 220, id=2, region_type="question_body")  # HEAVY(IoU≈0.227)
    assert classify_pair(a, b) == HEAVY
    result = validate_and_resolve(
        [a, b], 300, 300, mode="regions", min_region_area=15000.0
    )
    # shrink 취소 → reject fallback: 작은 쪽(b, id=2)이 탈락 → 개수 감소.
    ids = {r.id for r in result.regions}
    assert 2 not in ids
    assert any("reject" in act for act in result.report.actions)


# ===========================================================================
# §9 표 8 — 겹침 없음(DISJOINT) → 무변경, report.ok == True
# ===========================================================================
def test_case8_disjoint_no_change():
    a = _r(0, 0, 50, 50, id=1, region_type="question_body")
    b = _r(100, 100, 150, 150, id=2, region_type="question_body")
    assert classify_pair(a, b) == DISJOINT

    before = [(a.x1, a.y1, a.x2, a.y2), (b.x1, b.y1, b.x2, b.y2)]
    result = validate_and_resolve([a, b], 300, 300, mode="regions")
    after = [(r.x1, r.y1, r.x2, r.y2) for r in result.regions]
    assert after == before
    assert result.report.ok is True


# ===========================================================================
# §9 표 9 — 불변식 위반 입력(x1>x2) → fail-open, 원본 반환, report.ok == False
# ===========================================================================
def test_case9_invalid_invariant_fail_open():
    bad = _r(100, 0, 50, 100, id=1, region_type="question_body")  # x1>x2
    good = _r(0, 0, 30, 30, id=2, region_type="question_body")

    result = validate_and_resolve([bad, good], 300, 300, mode="regions")
    assert result.report.ok is False
    # 원본 그대로 반환(보정 안 함).
    assert result.regions[0] is bad and result.regions[1] is good


# ===========================================================================
# §9 표 10 — "플래그 off" 는 파이프라인 훅 관련.
# ===========================================================================
# 이 3단계는 검증기 미연결 상태이므로 파이프라인 skip 을 직접 만들 수 없다.
# 대신 "validate_and_resolve 를 호출하지 않으면 입력이 그대로다"를 확인한다.
# 실제 플래그 off 회귀는 파이프라인 연결 단계(설계 §10-4/5단계)에서 검증한다.
def test_case10_not_invoked_leaves_input_unchanged():
    a = _r(0, 0, 100, 100, id=1, region_type="question_body")
    b = _r(0, 80, 100, 180, id=2, region_type="question_body")
    snapshot = [(a.x1, a.y1, a.x2, a.y2), (b.x1, b.y1, b.x2, b.y2)]
    # 검증기를 호출하지 않으면 좌표 불변.
    assert [(a.x1, a.y1, a.x2, a.y2), (b.x1, b.y1, b.x2, b.y2)] == snapshot


# ===========================================================================
# §9b 표 11 — 원문 사이 figure 1개 → question_body 2개 + figure 1개, order 0/1/2
# ===========================================================================
def test_case11_split_one_figure():
    parent = _r(0, 100, 300, 430, id=1, region_type="full_problem")
    fig = _r(0, 180, 300, 360, id=2, region_type="figure", parent_region_id=1)

    ordered = split_question_body_by_separators(parent, [fig])
    qbs = [r for r in ordered if r.region_type == "question_body"]
    figs = [r for r in ordered if r.region_type == "figure"]
    assert len(qbs) == 2
    assert len(figs) == 1
    # order 0/1/2 위→아래.
    assert [r.order_index for r in ordered] == [0, 1, 2]
    assert ordered[0].region_type == "question_body"
    assert ordered[1].region_type == "figure"
    assert ordered[2].region_type == "question_body"


# ===========================================================================
# §9b 표 12 — 원문 사이 figure 2개 → question_body 3개 (N-분할)
# ===========================================================================
def test_case12_split_two_figures():
    parent = _r(0, 0, 300, 600, id=1, region_type="full_problem")
    f1 = _r(0, 100, 300, 200, id=2, region_type="figure", parent_region_id=1)
    f2 = _r(0, 350, 300, 450, id=3, region_type="graph", parent_region_id=1)

    ordered = split_question_body_by_separators(parent, [f1, f2])
    qbs = [r for r in ordered if r.region_type == "question_body"]
    assert len(qbs) == 3  # top..100, 200..350, 450..600
    # N-분할이므로 총 5개(qb 3 + 분리자 2), order 연속.
    assert [r.order_index for r in ordered] == list(range(len(ordered)))
    assert len(ordered) == 5


# ===========================================================================
# §9b 표 13 — figure 없음 → question_body 1개(분할 안 함)
# ===========================================================================
def test_case13_no_figure_single_body():
    parent = _r(0, 0, 300, 400, id=1, region_type="full_problem")
    # 자식은 텍스트류(분리자 아님) → 밴드 분리 안 됨.
    child = _r(10, 10, 100, 50, id=2, region_type="formula", parent_region_id=1)

    ordered = split_question_body_by_separators(parent, [child])
    qbs = [r for r in ordered if r.region_type == "question_body"]
    assert len(qbs) == 1


# ===========================================================================
# §9b 표 14 — 분리자 y겹침 2개 → union 후 1개 분리자로 처리
# ===========================================================================
def test_case14_overlapping_separators_union():
    parent = _r(0, 0, 300, 500, id=1, region_type="full_problem")
    # 두 분리자가 y로 겹침 → union 하나로 취급 → 밴드 = top..150, 350..500 = qb 2개.
    f1 = _r(0, 150, 300, 300, id=2, region_type="figure", parent_region_id=1)
    f2 = _r(0, 250, 300, 350, id=3, region_type="figure", parent_region_id=1)

    ordered = split_question_body_by_separators(parent, [f1, f2])
    qbs = [r for r in ordered if r.region_type == "question_body"]
    # union 된 분리자 밴드는 하나로 취급되므로 텍스트 밴드는 위/아래 2개.
    assert len(qbs) == 2


# ===========================================================================
# §9b 표 15 — 병합 조회 → assemble_question_body_text 가 order_index 순 결합
# ===========================================================================
def test_case15_assemble_question_body_text_order():
    qb2 = _r(0, 360, 300, 430, id=3, region_type="question_body",
             order_index=2, ocr_text="…일 때 f(3)의 값은?")
    fig = _r(0, 180, 300, 360, id=2, region_type="figure", order_index=1, ocr_text="GRAPH")
    qb1 = _r(0, 100, 300, 180, id=1, region_type="question_body",
             order_index=0, ocr_text="함수 f(x)에 대하여")

    # 입력 순서를 뒤섞어도 order_index 순으로 결합.
    text = assemble_question_body_text([qb2, fig, qb1])
    assert text == "함수 f(x)에 대하여\n…일 때 f(3)의 값은?"


def test_case15b_assemble_uses_text_fallback():
    qb = _r(0, 0, 10, 10, id=1, region_type="question_body", order_index=0, text="fallback")
    assert assemble_question_body_text([qb]) == "fallback"


# ===========================================================================
# 데이터 구조/리포트 기본값 검증
# ===========================================================================
def test_overlap_report_defaults():
    rep = OverlapReport()
    assert rep.ok is True
    assert rep.heavy == []
    assert rep.contained == []
    assert rep.out_of_bounds == []
    assert rep.choice_fixed == []
    assert rep.actions == []


def test_validate_regions_detects_heavy_without_mutation():
    a = _r(0, 0, 100, 100, id=1, region_type="question_body")
    b = _r(0, 60, 100, 160, id=2, region_type="question_body")  # 40px 겹침 → HEAVY
    report = validate_regions([a, b], 300, 300)
    assert report.heavy  # HEAVY 검출
    # validate_regions 는 보정하지 않으므로 원본 좌표 불변.
    assert (a.x1, a.y1, a.x2, a.y2) == (0, 0, 100, 100)


# ===========================================================================
# Property-based tests (hypothesis) — 순수 기하/불변식
# ===========================================================================
_COORD = st.floats(min_value=0, max_value=1000, allow_nan=False, allow_infinity=False)


@st.composite
def _heavy_pair(draw):
    """세로로 겹치는(HEAVY 후보) 큰 두 박스 쌍."""
    x1 = draw(st.floats(min_value=0, max_value=100, allow_nan=False))
    w = draw(st.floats(min_value=200, max_value=400, allow_nan=False))
    y1a = draw(st.floats(min_value=0, max_value=100, allow_nan=False))
    h = draw(st.floats(min_value=200, max_value=400, allow_nan=False))
    # b 를 세로로 조금 내려 겹치게.
    overlap = draw(st.floats(min_value=20, max_value=150, allow_nan=False))
    a = _r(x1, y1a, x1 + w, y1a + h)
    b = _r(x1, y1a + h - overlap, x1 + w, y1a + h - overlap + h)
    return a, b


@settings(max_examples=80, deadline=None)
@given(pair=_heavy_pair())
def test_property_shrink_removes_overlap(pair):
    """shrink 성공 시 두 박스의 겹침(작은 축)이 ≈0 이 된다."""
    a, b = pair
    xo_before = x_overlap(a.as_corner(), b.as_corner())
    yo_before = y_overlap(a.as_corner(), b.as_corner())
    ok = shrink_pair(a, b, min_region_area=1.0)
    if ok:
        # 덜 겹친 축이 해소되었는지 확인.
        if yo_before <= xo_before:
            assert y_overlap(a.as_corner(), b.as_corner()) == pytest.approx(0.0, abs=1e-6)
        else:
            assert x_overlap(a.as_corner(), b.as_corner()) == pytest.approx(0.0, abs=1e-6)


@settings(max_examples=80, deadline=None)
@given(
    px=_COORD, py=_COORD,
    pw=st.floats(min_value=50, max_value=500, allow_nan=False),
    ph=st.floats(min_value=50, max_value=500, allow_nan=False),
    cx=st.floats(min_value=-200, max_value=1200, allow_nan=False),
    cy=st.floats(min_value=-200, max_value=1200, allow_nan=False),
    cw=st.floats(min_value=1, max_value=300, allow_nan=False),
    ch=st.floats(min_value=1, max_value=300, allow_nan=False),
)
def test_property_clamp_to_parent_within_bounds(px, py, pw, ph, cx, cy, cw, ch):
    """clamp_to_parent 후 자식은 항상 부모 경계 내(tol=BOUNDARY_TOL)."""
    parent = _r(px, py, px + pw, py + ph, id=1, region_type="full_problem")
    child = _r(cx, cy, cx + cw, cy + ch, id=2)
    clamp_to_parent(child, parent, tol=BOUNDARY_TOL)
    assert contains(parent.as_corner(), child.as_corner(), tol=BOUNDARY_TOL)


@settings(max_examples=100, deadline=None)
@given(
    ax1=_COORD, ay1=_COORD,
    aw=st.floats(min_value=0, max_value=500, allow_nan=False),
    ah=st.floats(min_value=0, max_value=500, allow_nan=False),
    bx1=_COORD, by1=_COORD,
    bw=st.floats(min_value=0, max_value=500, allow_nan=False),
    bh=st.floats(min_value=0, max_value=500, allow_nan=False),
)
def test_property_classify_pair_returns_valid_constant(ax1, ay1, aw, ah, bx1, by1, bw, bh):
    """classify_pair 결과는 항상 4개 상수 중 하나."""
    a = _r(ax1, ay1, ax1 + aw, ay1 + ah)
    b = _r(bx1, by1, bx1 + bw, by1 + bh)
    assert classify_pair(a, b) in {CONTAINED, HEAVY, TOUCHING, DISJOINT}

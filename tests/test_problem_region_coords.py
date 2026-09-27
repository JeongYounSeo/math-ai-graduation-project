"""ProblemRegion 좌표 승격 테스트 (설계 §2).

검증 대상:
- ``set_box`` 로 x1..y2 컬럼과 bounding_box JSON 을 **동시 기록**.
- ``get_box`` read 우선순위: 컬럼이 있으면 컬럼, 없고 JSON 만 있으면 JSON 변환.
- parent_region_id / page_width / page_height 저장·조회.
- RegionType 신규 11종 + 기존 6종 값이 모두 존재.

db_session 픽스처(tests/conftest.py, 인메모리 SQLite)를 사용한다.
"""

from app.models.problem import Problem
from app.models.problem_region import ProblemRegion, RegionType


def _make_problem(session) -> Problem:
    """FK(problem_id) 제약을 만족시키기 위한 최소 Problem 생성."""
    problem = Problem(title="테스트 문제")
    session.add(problem)
    session.commit()
    session.refresh(problem)
    return problem


def _make_region(session, problem_id, **kwargs) -> ProblemRegion:
    defaults = dict(
        problem_id=problem_id,
        region_type=RegionType.FULL_PROBLEM.value,
        order_index=0,
        bounding_box={},
    )
    defaults.update(kwargs)
    region = ProblemRegion(**defaults)
    session.add(region)
    session.commit()
    session.refresh(region)
    return region


def test_set_box_writes_columns_and_bounding_box_together(db_session):
    """set_box 는 x1..y2 컬럼과 bounding_box JSON 을 동시에 기록한다."""
    problem = _make_problem(db_session)
    region = _make_region(db_session, problem.id)

    region.set_box((10.0, 20.0, 110.0, 220.0), page_width=1000.0, page_height=1400.0)
    db_session.commit()
    db_session.refresh(region)

    # 컬럼 기록 확인
    assert region.x1 == 10.0
    assert region.y1 == 20.0
    assert region.x2 == 110.0
    assert region.y2 == 220.0
    assert region.page_width == 1000.0
    assert region.page_height == 1400.0

    # bounding_box JSON 동시 기록 확인 ({left, top, right, bottom} 규약)
    assert region.bounding_box == {
        "left": 10.0,
        "top": 20.0,
        "right": 110.0,
        "bottom": 220.0,
    }


def test_set_box_accepts_corner_dict(db_session):
    """set_box 는 corner dict 입력도 받는다."""
    problem = _make_problem(db_session)
    region = _make_region(db_session, problem.id)

    region.set_box({"x1": 1.0, "y1": 2.0, "x2": 3.0, "y2": 4.0})
    db_session.commit()
    db_session.refresh(region)

    assert (region.x1, region.y1, region.x2, region.y2) == (1.0, 2.0, 3.0, 4.0)
    assert region.bounding_box == {"left": 1.0, "top": 2.0, "right": 3.0, "bottom": 4.0}


def test_get_box_prefers_columns(db_session):
    """get_box: x1..y2 컬럼이 있으면 컬럼 값을 반환한다(컬럼 우선)."""
    problem = _make_problem(db_session)
    # 컬럼과 JSON 이 서로 다른 값을 가지도록 일부러 불일치시켜 우선순위를 검증.
    region = _make_region(
        db_session,
        problem.id,
        x1=5.0,
        y1=6.0,
        x2=7.0,
        y2=8.0,
        bounding_box={"left": 100.0, "top": 200.0, "right": 300.0, "bottom": 400.0},
    )

    assert region.get_box() == (5.0, 6.0, 7.0, 8.0)


def test_get_box_falls_back_to_bounding_box_json(db_session):
    """get_box: 컬럼이 None 이고 bounding_box JSON 만 있으면 JSON 을 변환해 반환."""
    problem = _make_problem(db_session)
    region = _make_region(
        db_session,
        problem.id,
        bounding_box={"left": 11.0, "top": 22.0, "right": 33.0, "bottom": 44.0},
    )

    assert region.x1 is None
    assert region.get_box() == (11.0, 22.0, 33.0, 44.0)


def test_get_box_returns_none_when_no_coords(db_session):
    """get_box: 컬럼도 JSON 도 없으면 None."""
    problem = _make_problem(db_session)
    region = _make_region(db_session, problem.id, bounding_box={})

    assert region.get_box() is None


def test_parent_region_id_and_page_dims_persist(db_session):
    """parent_region_id, page_width/height 저장·조회."""
    problem = _make_problem(db_session)
    parent = _make_region(db_session, problem.id, region_type=RegionType.FULL_PROBLEM.value)
    child = _make_region(
        db_session,
        problem.id,
        region_type=RegionType.FIGURE.value,
        order_index=1,
        parent_region_id=parent.id,
        page_width=800.0,
        page_height=1200.0,
    )

    db_session.expire_all()
    reloaded = db_session.get(ProblemRegion, child.id)
    assert reloaded.parent_region_id == parent.id
    assert reloaded.page_width == 800.0
    assert reloaded.page_height == 1200.0


def test_region_type_has_new_and_legacy_values():
    """RegionType 에 신규 11종과 기존 6종 값이 모두 존재한다."""
    values = {rt.value for rt in RegionType}

    new_values = {
        "full_problem",
        "question_body",
        "condition_box",
        "figure",
        "graph",
        "table",
        "choice_group",
        "choice_option",
        "formula",
        "passage",
        "unknown",
    }
    legacy_values = {
        "QUESTION_TEXT",
        "DIAGRAM",
        "CHOICE_BOX",
        "STATEMENT_BOX",
        "TABLE",
        "OTHER",
    }

    assert new_values <= values
    assert legacy_values <= values
    # 기존 코드가 의존하는 멤버명/값 매핑도 유지되는지 확인.
    assert RegionType.QUESTION_TEXT.value == "QUESTION_TEXT"
    assert RegionType.TABLE.value == "TABLE"
    assert RegionType.TABLE_NEW.value == "table"

"""ProblemOcrApplyService 단위 테스트 (설계 §5).

인메모리 SQLite 엔진에 전체 모델을 등록하고 격리된 세션으로 서비스를
직접 검증한다. 실제 OCR/Claude/네트워크 호출은 전혀 없다(result dict 입력).

핵심 검증:
- multiple_choice + choices → ProblemChoice replace(index 1.., label ①..⑤,
  is_correct 전부 None). correct_answer 가 있어도 is_correct None 유지(추측 금지).
- multiple_choice 가 아니거나 choices 없음 → choice 미생성.
- full_problem region 자동 생성: crop_box 유효 & 기존 full_problem 없음 → 1개 생성,
  get_box() 가 crop_box→corner 변환값과 일치, bounding_box(JSON)도 채워짐.
- 이미 full_problem region 존재 → 새로 생성하지 않음(개수 불변).
- crop_box 무효/없음 → full_problem region 생성 생략(예외 없음).
- 반환 요약 dict 값 검증.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db_base import Base

# 전체 모델을 import 해 Base.metadata 에 등록한다.
import app.models.problem  # noqa: F401
import app.models.source_pdf  # noqa: F401
import app.models.concept_module  # noqa: F401
import app.models.solution_module  # noqa: F401
import app.models.type_combination  # noqa: F401
import app.models.generated_problem  # noqa: F401
import app.models.passage  # noqa: F401
import app.models.problem_region  # noqa: F401
import app.models.problem_region_item  # noqa: F401
import app.models.problem_choice  # noqa: F401

from app.models.problem import Problem
from app.models.problem_region import ProblemRegion, RegionType
from app.repositories.problem_choice_repository import (
    ProblemChoiceRepository,
    CIRCLED_LABELS,
)
from app.services.problem_ocr_apply_service import ProblemOcrApplyService
from app.utils.box_geometry import xywh_to_corner


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _make_problem(db, crop_box=None):
    problem = Problem(
        title="",
        source_type="pdf",
        crop_box=crop_box if crop_box is not None else {},
    )
    db.add(problem)
    db.commit()
    db.refresh(problem)
    return problem


# --------------------------------------------------------------------- #
# 객관식 choices 저장
# --------------------------------------------------------------------- #
def test_multiple_choice_creates_choices(db_session):
    problem = _make_problem(db_session)
    service = ProblemOcrApplyService(db_session)

    result = {
        "answer_type": "multiple_choice",
        "choices": ["보기 1", "보기 2", "보기 3"],
    }
    summary = service.apply_ocr_result(problem.id, result)

    assert summary["choices_replaced"] == 3

    choices = ProblemChoiceRepository(db_session).get_by_problem_id(problem.id)
    assert len(choices) == 3
    assert [c.choice_index for c in choices] == [1, 2, 3]
    assert [c.choice_label for c in choices] == CIRCLED_LABELS[:3]
    assert [c.text for c in choices] == ["보기 1", "보기 2", "보기 3"]
    # 정답 추측 금지: 전부 None.
    assert all(c.is_correct is None for c in choices)


def test_correct_answer_does_not_set_is_correct(db_session):
    """correct_answer 가 주어져도 is_correct 는 전부 None(정답 추측 금지)."""
    problem = _make_problem(db_session)
    service = ProblemOcrApplyService(db_session)

    result = {
        "answer_type": "multiple_choice",
        "choices": ["가", "나", "다", "라"],
        "correct_answer": 2,  # 주어져도 무시되어야 함
    }
    service.apply_ocr_result(problem.id, result)

    choices = ProblemChoiceRepository(db_session).get_by_problem_id(problem.id)
    assert len(choices) == 4
    assert all(c.is_correct is None for c in choices)
    assert all(c.is_distractor is None for c in choices)


def test_not_multiple_choice_creates_no_choices(db_session):
    problem = _make_problem(db_session)
    service = ProblemOcrApplyService(db_session)

    summary = service.apply_ocr_result(
        problem.id, {"answer_type": "short_answer", "choices": ["가", "나"]}
    )
    assert summary["choices_replaced"] == 0
    assert ProblemChoiceRepository(db_session).get_by_problem_id(problem.id) == []


def test_missing_choices_creates_no_choices(db_session):
    problem = _make_problem(db_session)
    service = ProblemOcrApplyService(db_session)

    # choices 키 없음
    summary = service.apply_ocr_result(problem.id, {"answer_type": "multiple_choice"})
    assert summary["choices_replaced"] == 0
    # 빈 리스트도 미생성
    summary2 = service.apply_ocr_result(
        problem.id, {"answer_type": "multiple_choice", "choices": []}
    )
    assert summary2["choices_replaced"] == 0
    assert ProblemChoiceRepository(db_session).get_by_problem_id(problem.id) == []


# --------------------------------------------------------------------- #
# full_problem region 자동 생성
# --------------------------------------------------------------------- #
def test_full_problem_region_created_from_result_crop_box(db_session):
    problem = _make_problem(db_session)
    service = ProblemOcrApplyService(db_session)

    crop_box = {"x": 10, "y": 20, "width": 100, "height": 200}
    summary = service.apply_ocr_result(
        problem.id,
        {"crop_box": crop_box, "page_width": 800, "page_height": 1200},
    )

    assert summary["full_problem_region_created"] is True

    regions = (
        db_session.query(ProblemRegion)
        .filter(ProblemRegion.problem_id == problem.id)
        .all()
    )
    assert len(regions) == 1
    region = regions[0]
    assert region.region_type == RegionType.FULL_PROBLEM.value
    assert region.order_index == 0

    # get_box() 가 crop_box→corner 변환값과 일치해야 한다.
    assert region.get_box() == xywh_to_corner(crop_box)
    # bounding_box(JSON) 도 채워져 있어야 한다({left,top,right,bottom}).
    assert region.bounding_box == {
        "left": 10.0,
        "top": 20.0,
        "right": 110.0,
        "bottom": 220.0,
    }
    assert region.page_width == 800.0
    assert region.page_height == 1200.0


def test_full_problem_region_falls_back_to_problem_crop_box(db_session):
    """result 에 crop_box 가 없으면 Problem.crop_box 를 사용한다."""
    problem = _make_problem(
        db_session, crop_box={"x": 5, "y": 5, "width": 50, "height": 60}
    )
    service = ProblemOcrApplyService(db_session)

    summary = service.apply_ocr_result(problem.id, {})
    assert summary["full_problem_region_created"] is True

    regions = (
        db_session.query(ProblemRegion)
        .filter(ProblemRegion.problem_id == problem.id)
        .all()
    )
    assert len(regions) == 1
    assert regions[0].get_box() == (5.0, 5.0, 55.0, 65.0)


def test_full_problem_region_not_created_when_exists(db_session):
    """이미 full_problem region 이 있으면 새로 생성하지 않는다(개수 불변)."""
    problem = _make_problem(
        db_session, crop_box={"x": 0, "y": 0, "width": 100, "height": 100}
    )
    # 사전 full_problem region 1개 삽입
    existing = ProblemRegion(
        problem_id=problem.id,
        region_type=RegionType.FULL_PROBLEM.value,
        order_index=0,
        bounding_box={"left": 1, "top": 1, "right": 2, "bottom": 2},
    )
    db_session.add(existing)
    db_session.commit()

    service = ProblemOcrApplyService(db_session)
    summary = service.apply_ocr_result(
        problem.id, {"crop_box": {"x": 0, "y": 0, "width": 100, "height": 100}}
    )

    assert summary["full_problem_region_created"] is False
    regions = (
        db_session.query(ProblemRegion)
        .filter(ProblemRegion.problem_id == problem.id)
        .all()
    )
    assert len(regions) == 1  # 개수 불변


def test_full_problem_region_skipped_when_crop_box_invalid(db_session):
    """crop_box 가 무효/없으면 생성 생략(예외 없음)."""
    problem = _make_problem(db_session, crop_box={})  # Problem.crop_box 도 무효
    service = ProblemOcrApplyService(db_session)

    # width=0 → 무효
    summary = service.apply_ocr_result(
        problem.id, {"crop_box": {"x": 0, "y": 0, "width": 0, "height": 100}}
    )
    assert summary["full_problem_region_created"] is False

    # crop_box 아예 없음 + Problem.crop_box 도 무효
    summary2 = service.apply_ocr_result(problem.id, {})
    assert summary2["full_problem_region_created"] is False

    regions = (
        db_session.query(ProblemRegion)
        .filter(ProblemRegion.problem_id == problem.id)
        .all()
    )
    assert regions == []


# --------------------------------------------------------------------- #
# 반환 요약 dict / 방어적 처리
# --------------------------------------------------------------------- #
def test_summary_combines_both_actions(db_session):
    problem = _make_problem(db_session)
    service = ProblemOcrApplyService(db_session)

    summary = service.apply_ocr_result(
        problem.id,
        {
            "answer_type": "multiple_choice",
            "choices": ["a", "b"],
            "crop_box": {"x": 1, "y": 2, "width": 3, "height": 4},
        },
    )
    assert summary == {"choices_replaced": 2, "full_problem_region_created": True}


def test_missing_problem_returns_empty_summary(db_session):
    service = ProblemOcrApplyService(db_session)
    summary = service.apply_ocr_result(
        99999, {"answer_type": "multiple_choice", "choices": ["a"]}
    )
    assert summary == {"choices_replaced": 0, "full_problem_region_created": False}

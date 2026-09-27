"""apply_ocr_result 연결 + Problem.choices 스키마 확장 통합 테스트 (2026-09-17).

기존 관례(test_problem_choice_router.py)를 따른다:
- Base 는 app.core.db_base 에서 가져오고, 전체 모델을 import 해 metadata 에 등록.
- 인메모리 SQLite + StaticPool 로 격리.
- 엔드포인트 테스트는 app.main 전체를 로드하지 않고 경량 FastAPI 앱에 problem_router 만
  마운트해 다른 서브시스템/네트워크 의존을 배제한다.

검증 대상:
1. Problem 모델에 choices/answer_type 컬럼이 존재
2. apply_ocr_result 가 객관식 보기를 ProblemChoice 로 저장하고 Problem.choices 동기화
3. is_correct 는 전부 None (정답 추측 금지)
4. crop_box 로 full_problem region 자동 생성, 재실행 시 중복 생성 안 함
5. choices 어댑터: CHOICE_BOX items → choices 리스트 조립
6. POST /{id}/apply-ocr 엔드포인트 동작 (200 / 404)
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db_base import Base
from app.core.database import get_db

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
from app.models.problem_region_item import ProblemRegionItem
from app.services.problem_ocr_apply_service import ProblemOcrApplyService
from app.services.pdf_import_service import PDFImportService
from app.repositories.problem_choice_repository import ProblemChoiceRepository
from app.repositories.problem_region_repository import ProblemRegionRepository
from app.routers import problem_router


@pytest.fixture
def db():
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
    p = Problem(
        title="t",
        source_type="pdf",
        crop_box=crop_box or {"x": 10, "y": 20, "width": 300, "height": 400},
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def test_problem_has_new_columns():
    assert hasattr(Problem, "choices")
    assert hasattr(Problem, "answer_type")


def test_apply_ocr_creates_choices_and_syncs_problem(db):
    p = _make_problem(db)
    result = {"answer_type": "multiple_choice", "choices": ["1", "2", "3", "4", "5"]}
    summary = ProblemOcrApplyService(db).apply_ocr_result(p.id, result)

    assert summary["choices_replaced"] == 5
    choices = ProblemChoiceRepository(db).get_by_problem_id(p.id)
    assert [c.text for c in choices] == ["1", "2", "3", "4", "5"]
    # 정답 추측 금지
    assert all(c.is_correct is None for c in choices)
    # Problem.choices 동기화
    db.refresh(p)
    assert p.choices == ["1", "2", "3", "4", "5"]
    assert p.answer_type == "multiple_choice"


def test_apply_ocr_creates_full_problem_region_once(db):
    p = _make_problem(db)
    summary = ProblemOcrApplyService(db).apply_ocr_result(p.id, {})
    assert summary["full_problem_region_created"] is True

    regions = ProblemRegionRepository(db).get_by_problem_id(p.id)
    fps = [r for r in regions if r.region_type == RegionType.FULL_PROBLEM.value]
    assert len(fps) == 1
    assert fps[0].get_box() == (10.0, 20.0, 310.0, 420.0)

    # 재실행 시 중복 생성 안 함
    summary2 = ProblemOcrApplyService(db).apply_ocr_result(p.id, {})
    assert summary2["full_problem_region_created"] is False


def test_apply_ocr_skips_choices_when_empty(db):
    """choices 없으면 보기 저장 skip (Vision 미연동 시 회귀 방지)."""
    p = _make_problem(db)
    summary = ProblemOcrApplyService(db).apply_ocr_result(
        p.id, {"answer_type": "multiple_choice"}
    )
    assert summary["choices_replaced"] == 0
    assert ProblemChoiceRepository(db).get_by_problem_id(p.id) == []


def test_choices_adapter_from_choice_box_items(db):
    """_build_ocr_result_from_regions: CHOICE_BOX items → choices 조립."""
    p = _make_problem(db)
    region = ProblemRegion(
        problem_id=p.id,
        region_type=RegionType.CHOICE_BOX.value,
        order_index=0,
        bounding_box={"left": 0, "top": 0, "right": 100, "bottom": 50},
    )
    db.add(region)
    db.commit()
    db.refresh(region)
    for i, txt in enumerate(["2", "4", "6", "8", "10"]):
        db.add(
            ProblemRegionItem(
                region_id=region.id, label=str(i + 1), order_index=i, text=txt
            )
        )
    db.commit()

    svc = PDFImportService(db)
    result = svc._build_ocr_result_from_regions(p)
    assert result["answer_type"] == "multiple_choice"
    assert result["choices"] == ["2", "4", "6", "8", "10"]
    assert result["crop_box"] == p.crop_box


def _add_choice_option(db, problem_id, order_index, y1, text):
    """choice_option region 하나를 생성한다(텍스트는 latex_text 에 저장)."""
    r = ProblemRegion(
        problem_id=problem_id,
        region_type=RegionType.CHOICE_OPTION.value,
        order_index=order_index,
        bounding_box={"left": 0, "top": y1, "right": 100, "bottom": y1 + 20},
        latex_text=text,
    )
    db.add(r)
    db.commit()
    return r


def test_choices_adapter_from_choice_options(db):
    """신규 choice_option region 들 → choices (order_index 순)."""
    p = _make_problem(db)
    # 일부러 순서를 뒤섞어 넣고 order_index 로 정렬되는지 확인.
    _add_choice_option(db, p.id, order_index=2, y1=200, text="C")
    _add_choice_option(db, p.id, order_index=0, y1=100, text="A")
    _add_choice_option(db, p.id, order_index=1, y1=150, text="B")

    svc = PDFImportService(db)
    result = svc._build_ocr_result_from_regions(p)
    assert result["answer_type"] == "multiple_choice"
    assert result["choices"] == ["A", "B", "C"]


def test_choices_adapter_sorts_by_y_when_order_index_tied(db):
    """order_index 가 동일하면 get_box() top(y1) 순으로 정렬한다.

    (order_index 는 NOT NULL 이므로 None 을 넣을 수 없다. 동일 값으로 통일해
    2차 정렬 키인 y1 이 실제 순서를 결정하는지 검증한다.)
    """
    p = _make_problem(db)
    _add_choice_option(db, p.id, order_index=0, y1=300, text="Z")
    _add_choice_option(db, p.id, order_index=0, y1=100, text="X")
    _add_choice_option(db, p.id, order_index=0, y1=200, text="Y")

    svc = PDFImportService(db)
    result = svc._build_ocr_result_from_regions(p)
    assert result["choices"] == ["X", "Y", "Z"]


def test_choice_options_take_priority_over_choice_box(db):
    """choice_option 과 CHOICE_BOX 가 공존하면 choice_option 을 우선한다."""
    p = _make_problem(db)
    # 신규 방식
    _add_choice_option(db, p.id, order_index=0, y1=100, text="new1")
    _add_choice_option(db, p.id, order_index=1, y1=120, text="new2")
    # 기존 방식(같은 문제에 함께 존재)
    box = ProblemRegion(
        problem_id=p.id,
        region_type=RegionType.CHOICE_BOX.value,
        order_index=5,
        bounding_box={"left": 0, "top": 0, "right": 100, "bottom": 50},
    )
    db.add(box)
    db.commit()
    db.refresh(box)
    for i, t in enumerate(["old1", "old2"]):
        db.add(
            ProblemRegionItem(
                region_id=box.id, label=str(i + 1), order_index=i, text=t
            )
        )
    db.commit()

    svc = PDFImportService(db)
    result = svc._build_ocr_result_from_regions(p)
    assert result["choices"] == ["new1", "new2"]


def test_single_choice_option_falls_back_to_choice_box(db):
    """choice_option 이 1개뿐(2개 미만)이면 신규 방식 무시하고 CHOICE_BOX fallback."""
    p = _make_problem(db)
    _add_choice_option(db, p.id, order_index=0, y1=100, text="lonely")
    box = ProblemRegion(
        problem_id=p.id,
        region_type=RegionType.CHOICE_BOX.value,
        order_index=5,
        bounding_box={"left": 0, "top": 0, "right": 100, "bottom": 50},
    )
    db.add(box)
    db.commit()
    db.refresh(box)
    for i, t in enumerate(["a", "b", "c"]):
        db.add(
            ProblemRegionItem(
                region_id=box.id, label=str(i + 1), order_index=i, text=t
            )
        )
    db.commit()

    svc = PDFImportService(db)
    result = svc._build_ocr_result_from_regions(p)
    assert result["choices"] == ["a", "b", "c"]


def test_apply_ocr_endpoint(db):
    def override_get_db():
        yield db

    app = FastAPI()
    app.include_router(problem_router.router, prefix="/problems")
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        p = _make_problem(db)
        resp = client.post(
            f"/problems/{p.id}/apply-ocr",
            json={"answer_type": "multiple_choice", "choices": ["1", "2", "3"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["choices_replaced"] == 3
        assert body["full_problem_region_created"] is True

        # 404 케이스
        resp404 = client.post("/problems/999999/apply-ocr", json={})
        assert resp404.status_code == 404

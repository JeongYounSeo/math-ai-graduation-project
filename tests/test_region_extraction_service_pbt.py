"""TASK 8.3/8.4/8.6/8.7/8.9/8.10/8.12/8.13/8.16/8.17 —
ProblemRegionExtractionService 속성 기반 테스트.

Claude 호출은 전부 FakeVisionClient(configured=True)로 대체하므로 네트워크가
발생하지 않는다(Req 15). 영역 파싱/정렬/조립은 실제 서비스 로직을 통과하며,
영속화가 필요한 속성은 db_session 에 실제 ProblemRegion/Item 행을 만들고 조회해
검증한다.

각 속성 테스트는 설계 문서의 단일 Correctness Property를 구현하고,
`@settings(max_examples=100)` 이상과 태그 주석을 갖는다.

Requirements: 1.4, 1.6, 1.7, 2.1, 2.4, 2.5, 2.6, 3.1, 3.4, 3.5, 4.1, 4.2, 4.3,
7.5, 11.2, 11.4, 11.6, 14.1, 14.2
"""

import contextlib

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from PIL import Image
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db_base import Base
from app.models.problem import Problem
from app.models.problem_region import ProblemRegion, RegionType
from app.models.problem_region_item import ProblemRegionItem
from app.models.source_pdf import SourcePDF
from app.services.problem_region_extraction_service import (
    ProblemRegionExtractionService,
    RegionExtractionResult,
)

# 모든 모델을 import 해 Base.metadata 에 등록한다(아래 create_all 대상).
# create_tables()(app/core/database.py)가 등록하는 전체 모델을 빠짐없이 import 해야
# _PBT_ENGINE 에 모든 테이블이 생성되고, _fresh_session 정리 루프가
# Base.metadata.sorted_tables 를 순회할 때 실제로 존재하는 테이블만 남는다.
import app.models.problem  # noqa: F401
import app.models.source_pdf  # noqa: F401
import app.models.concept_module  # noqa: F401
import app.models.solution_module  # noqa: F401
import app.models.type_combination  # noqa: F401
import app.models.generated_problem  # noqa: F401
import app.models.passage  # noqa: F401
import app.models.problem_region  # noqa: F401
import app.models.problem_region_item  # noqa: F401
import app.models.crop_review  # noqa: F401

from tests._region_fixtures import (
    CHOICE_LABELS,
    STATEMENT_LABELS,
    FakeVisionClient,
    bounding_box_strategy,
    labeled_items_strategy,
    regions_response_strategy,
)

VALID_REGION_TYPES = {rt.value for rt in RegionType}
_IMAGE_SIZE = (200, 200)


# ---------------------------------------------------------------------------
# 격리된 세션 팩토리
# ---------------------------------------------------------------------------
# hypothesis 는 하나의 테스트 함수 안에서 수많은 예시를 반복 실행한다. pytest 의
# function-scoped `db_session` 은 함수당 1개뿐이라 예시마다 상태가 누적되고 고정
# source_pdf_id 가 UNIQUE 제약을 위반한다. 그래서 각 예시마다 완전히 격리된
# 인메모리 SQLite 세션을 새로 만든다.
# 모듈 레벨에서 인메모리 엔진을 **한 번만** 만든다. hypothesis 는 한 테스트
# 함수 안에서 수백 개 예시를 반복하는데, 예시마다 engine 을 새로 만들고
# create_all/dispose 하면(과거 구현) shrink 단계에서 수백~수천 번 반복되며
# 사실상 hang 한다. 엔진은 재사용하고, 예시 격리는 매 사용 후 전체 테이블 데이터를
# 삭제(child -> parent 순)해 UNIQUE 제약 충돌을 막는 방식으로 대체한다.
_PBT_ENGINE = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


@event.listens_for(_PBT_ENGINE, "connect")
def _pbt_pragma(dbapi_conn, _):  # noqa: ANN001
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


Base.metadata.create_all(bind=_PBT_ENGINE)
_PBT_Session = sessionmaker(autocommit=False, autoflush=False, bind=_PBT_ENGINE)


@contextlib.contextmanager
def _fresh_session():
    session = _PBT_Session()
    try:
        yield session
    finally:
        session.rollback()
        # 예시 간 격리: 모든 테이블 데이터를 제거한다(자식 -> 부모 순, FK 안전).
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()
        session.close()


def _write_image(tmp_path, size=_IMAGE_SIZE):
    path = tmp_path / "problem.png"
    Image.new("RGB", size, (255, 255, 255)).save(path)
    return str(path)


def _make_problem(session, image_path, source_pdf_id="PDF_TEST0001"):
    """FK 부모(source_pdfs) + Problem 행을 만들어 커밋하고 반환한다.

    Problem.source_pdf_id 는 String("PDF_XXX") 이므로 그대로 사용한다.
    """
    src = SourcePDF(
        source_pdf_id=source_pdf_id,
        original_filename="orig.pdf",
        stored_filename="stored.pdf",
        file_path=f"uploads/pdfs/{source_pdf_id}.pdf",
    )
    session.add(src)
    session.commit()

    problem = Problem(
        title="",
        source_type="pdf",
        source_pdf_id=source_pdf_id,
        page_number=1,
        problem_image_path=image_path,
    )
    session.add(problem)
    session.commit()
    session.refresh(problem)
    return problem


def _run(session, image_path, raw_json):
    """FakeVisionClient(raw_json)로 서비스를 실행하고 (problem, result, client)를 반환."""
    problem = _make_problem(session, image_path)
    client = FakeVisionClient(raw_json=raw_json, configured=True)
    service = ProblemRegionExtractionService(session, vision_client=client)
    result = service.extract_regions(problem)
    return problem, result, client


def _persisted_regions(session, problem_id):
    return (
        session.query(ProblemRegion)
        .filter(ProblemRegion.problem_id == problem_id)
        .order_by(ProblemRegion.order_index)
        .all()
    )


# 각 예시마다 새 이미지 파일을 tmp 디렉터리에 쓴다. tmp_path 는 function-scoped
# 픽스처이므로 해당 health check 만 억제한다(파일은 예시마다 덮어써도 무방).
_ST = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


# ===========================================================================
# Property 1
# ===========================================================================
# Feature: problem-region-vision-ocr, Property 1: 모든 영역은 유효한 Region_Type을 갖는다
@_ST
@given(payload=regions_response_strategy())
def test_property_1_valid_region_types(tmp_path, payload):
    image_path = _write_image(tmp_path)
    with _fresh_session() as session:
        problem, result, _ = _run(session, image_path, payload)

        assert result.success is True
        regions = _persisted_regions(session, problem.id)
        assert len(regions) == len(payload["regions"])
        for region in regions:
            assert region.region_type in VALID_REGION_TYPES


# ===========================================================================
# Property 2
# ===========================================================================
# Feature: problem-region-vision-ocr, Property 2: 영역 order_index는 (top, left) 정렬로 0-기반 연속·유일이다
@_ST
@given(payload=regions_response_strategy())
def test_property_2_order_index_contiguous_and_sorted(tmp_path, payload):
    image_path = _write_image(tmp_path)
    with _fresh_session() as session:
        problem, result, _ = _run(session, image_path, payload)

        assert result.success is True
        regions = _persisted_regions(session, problem.id)
        n = len(regions)

        # 0-기반 연속·유일.
        assert {r.order_index for r in regions} == set(range(n))

        # order_index 순으로 (top, left) 비감소.
        keys = []
        for r in regions:  # 이미 order_index 오름차순.
            bbox = r.bounding_box or {}
            top = bbox.get("top")
            left = bbox.get("left")
            # 유효 박스가 없는 영역은 맨 뒤(inf)로 정렬됨.
            keys.append(
                (float("inf"), float("inf")) if top is None else (top, left)
            )
        assert keys == sorted(keys)


# ===========================================================================
# Property 3
# ===========================================================================
# Feature: problem-region-vision-ocr, Property 3: confidence는 항상 null이거나 0.0~1.0 범위 내이다
@_ST
@given(payload=regions_response_strategy())
def test_property_3_confidence_null_or_in_range(tmp_path, payload):
    image_path = _write_image(tmp_path)
    with _fresh_session() as session:
        problem, result, _ = _run(session, image_path, payload)

        assert result.success is True
        for region in _persisted_regions(session, problem.id):
            if region.confidence is not None:
                assert 0.0 <= region.confidence <= 1.0


# ===========================================================================
# Property 5
# ===========================================================================
# Feature: problem-region-vision-ocr, Property 5: 다이어그램 영역은 OCR/LaTeX 텍스트를 갖지 않는다
@_ST
@given(payload=regions_response_strategy())
def test_property_5_diagram_has_no_text(tmp_path, payload):
    image_path = _write_image(tmp_path)
    with _fresh_session() as session:
        problem, result, _ = _run(session, image_path, payload)

        assert result.success is True
        for region in _persisted_regions(session, problem.id):
            if region.region_type == RegionType.DIAGRAM.value:
                assert region.ocr_text is None
                assert region.latex_text is None


# ===========================================================================
# Property 4
# ===========================================================================
# Feature: problem-region-vision-ocr, Property 4: 텍스트 영역은 OCR을 시도하고 실패는 격리된다
@_ST
@given(
    ocr_texts=st.lists(
        st.one_of(st.none(), st.just(""), st.text(min_size=1, max_size=20)),
        min_size=1,
        max_size=6,
    )
)
def test_property_4_text_ocr_attempt_and_isolation(tmp_path, ocr_texts):
    # 모든 영역을 QUESTION_TEXT(텍스트 영역)로 두고 ocr_text 유무를 섞는다.
    regions = []
    for i, ocr in enumerate(ocr_texts):
        regions.append(
            {
                "region_type": "QUESTION_TEXT",
                "bounding_box": {
                    "left": 0,
                    "top": i * 10,
                    "right": 50,
                    "bottom": i * 10 + 9,
                },
                "ocr_text": ocr,
                "latex_text": None,
                "confidence": None,
            }
        )
    payload = {"regions": regions}

    image_path = _write_image(tmp_path)
    with _fresh_session() as session:
        problem, result, _ = _run(session, image_path, payload)

        assert result.success is True
        persisted = _persisted_regions(session, problem.id)
        assert len(persisted) == len(ocr_texts)

        # 각 영역: 비어있지 않은 ocr_text는 채워지고, 실패(빈/None)는 두 필드 모두 null.
        # 실패한 영역이 하나라도 있으면 result.errors에 표시가 남는다(격리).
        failure_seen = False
        for region in persisted:
            if region.ocr_text is None:
                assert region.latex_text is None
                failure_seen = True
            else:
                assert region.ocr_text.strip() != ""
        if any((o is None or not o.strip()) for o in ocr_texts):
            assert failure_seen
            assert any("텍스트 추출 실패" in e for e in result.errors)


# ===========================================================================
# Property 6
# ===========================================================================
# Feature: problem-region-vision-ocr, Property 6: 바운딩 박스 클램프는 항상 경계 내이거나 무효 판정이다
@_ST
@given(
    boxes=st.lists(
        st.fixed_dictionaries(
            {
                "left": st.integers(min_value=-50, max_value=250),
                "top": st.integers(min_value=-50, max_value=250),
                "width": st.integers(min_value=1, max_value=300),
                "height": st.integers(min_value=1, max_value=300),
            }
        ),
        min_size=1,
        max_size=5,
    )
)
def test_property_6_bbox_clamp_within_bounds_or_invalid(tmp_path, boxes):
    width, height = _IMAGE_SIZE
    regions = []
    for i, b in enumerate(boxes):
        regions.append(
            {
                "region_type": "DIAGRAM",
                "bounding_box": {
                    "left": b["left"],
                    "top": b["top"],
                    "right": b["left"] + b["width"],
                    "bottom": b["top"] + b["height"],
                },
                "ocr_text": None,
                "latex_text": None,
                "confidence": 0.5,
            }
        )
    payload = {"regions": regions}

    image_path = _write_image(tmp_path, size=_IMAGE_SIZE)
    with _fresh_session() as session:
        problem, result, _ = _run(session, image_path, payload)

        assert result.success is True
        for region in _persisted_regions(session, problem.id):
            if region.image_path:
                # 크롭 성공 → 실제 파일이 존재하고 경계 안에서 잘렸다.
                with Image.open(region.image_path) as crop:
                    cw, ch = crop.size
                assert 1 <= cw <= width
                assert 1 <= ch <= height
            else:
                # 크롭 생략 → image_path 비어있고 오류 표시가 남는다(Req 3.5).
                assert region.image_path is None


# ===========================================================================
# Property 7
# ===========================================================================
# Feature: problem-region-vision-ocr, Property 7: 라벨 항목은 개수가 보존되고 라벨이 원문 그대로 유지된다
@_ST
@given(
    region_type=st.sampled_from(["CHOICE_BOX", "STATEMENT_BOX"]),
    items=labeled_items_strategy(),
)
def test_property_7_item_count_and_labels_preserved(
    tmp_path, region_type, items
):
    payload = {
        "regions": [
            {
                "region_type": region_type,
                "bounding_box": {"left": 0, "top": 0, "right": 100, "bottom": 100},
                "ocr_text": "박스",
                "latex_text": None,
                "confidence": None,
                "items": items,
            }
        ]
    }

    image_path = _write_image(tmp_path)
    with _fresh_session() as session:
        problem, result, _ = _run(session, image_path, payload)

        assert result.success is True
        region = _persisted_regions(session, problem.id)[0]
        persisted_items = (
            session.query(ProblemRegionItem)
            .filter(ProblemRegionItem.region_id == region.id)
            .order_by(ProblemRegionItem.order_index)
            .all()
        )

        # 개수 보존(입력 1~10, 상한 내이므로 그대로).
        assert len(persisted_items) == len(items)
        # 라벨 원문 그대로 보존.
        assert [it.label for it in persisted_items] == [it["label"] for it in items]


# ===========================================================================
# Property 8
# ===========================================================================
# Feature: problem-region-vision-ocr, Property 8: 라벨 항목 order_index는 읽기 순서로 0-기반 연속·유일이다
@_ST
@given(items=labeled_items_strategy())
def test_property_8_item_order_index_reading_order(tmp_path, items):
    payload = {
        "regions": [
            {
                "region_type": "CHOICE_BOX",
                "bounding_box": {"left": 0, "top": 0, "right": 100, "bottom": 100},
                "ocr_text": "박스",
                "latex_text": None,
                "confidence": None,
                "items": items,
            }
        ]
    }

    image_path = _write_image(tmp_path)
    with _fresh_session() as session:
        problem, result, _ = _run(session, image_path, payload)

        assert result.success is True
        region = _persisted_regions(session, problem.id)[0]
        persisted_items = (
            session.query(ProblemRegionItem)
            .filter(ProblemRegionItem.region_id == region.id)
            .all()
        )
        m = len(persisted_items)
        # 0-기반 연속·유일.
        assert {it.order_index for it in persisted_items} == set(range(m))
        # order_index 순서가 입력 읽기 순서를 반영.
        ordered = sorted(persisted_items, key=lambda it: it.order_index)
        assert [it.label for it in ordered] == [it["label"] for it in items]


# ===========================================================================
# Property 13
# ===========================================================================
# Feature: problem-region-vision-ocr, Property 13: 조립 캐시는 정렬된 영역 내용의 연결과 같다
@_ST
@given(payload=regions_response_strategy())
def test_property_13_assembled_cache_is_ordered_concat(tmp_path, payload):
    image_path = _write_image(tmp_path)
    with _fresh_session() as session:
        problem, result, _ = _run(session, image_path, payload)

        assert result.success is True
        session.refresh(problem)
        regions = _persisted_regions(session, problem.id)

        if not regions:
            # 영역 없음 → 빈 값(Req 11.6).
            assert problem.raw_ocr_text == ""
            assert problem.latex_text == ""
            assert problem.raw_text == ""
            return

        ordered = sorted(regions, key=lambda r: (r.order_index, r.id))
        expected_ocr = "\n".join(
            r.ocr_text for r in ordered if r.ocr_text is not None
        )
        assert problem.raw_ocr_text == expected_ocr
        # raw_text 는 ocr 조립본을 미러링한다.
        assert problem.raw_text == expected_ocr


# ===========================================================================
# Property 10
# ===========================================================================
# Feature: problem-region-vision-ocr, Property 10: 정상 동작 시 이미지당 Claude 호출은 정확히 1회이다
@_ST
@given(payload=regions_response_strategy())
def test_property_10_exactly_one_vision_call(tmp_path, payload):
    image_path = _write_image(tmp_path)
    with _fresh_session() as session:
        problem, result, client = _run(session, image_path, payload)

        assert result.success is True
        assert client.call_count == 1

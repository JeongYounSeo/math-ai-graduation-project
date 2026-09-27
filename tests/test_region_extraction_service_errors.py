"""TASK 8.18 — ProblemRegionExtractionService 오류 경로 예시/엣지 테스트.

Claude 호출은 FakeVisionClient로 대체하여 네트워크 없음(Req 15).

검증 대상:
- 이미지 읽기 불가 (Req 1.2)
- 자격증명 폴백 + warning 로그 1회 (Req 6.1, 6.4)
- malformed 부분 저장 없음 (Req 14.5)
- 빈 영역 → 성공 + 빈 조립 캐시 (Req 11.6)
- 지문 OCR 실패 시 미저장 (Req 5.5)
"""

import logging

import pytest
from PIL import Image

from app.models.problem import Problem
from app.models.problem_region import ProblemRegion
from app.models.source_pdf import SourcePDF
from app.services.problem_region_extraction_service import (
    ProblemRegionExtractionService,
)

from tests._region_fixtures import (
    FakeVisionClient,
    make_vision_empty,
    make_vision_malformed,
    make_vision_success_json,
)


def _write_image(tmp_path):
    path = tmp_path / "problem.png"
    Image.new("RGB", (120, 120), (255, 255, 255)).save(path)
    return str(path)


def _make_problem(db_session, image_path, source_pdf_id="PDF_ERR00001"):
    src = SourcePDF(
        source_pdf_id=source_pdf_id,
        original_filename="orig.pdf",
        stored_filename="stored.pdf",
        file_path=f"uploads/pdfs/{source_pdf_id}.pdf",
    )
    db_session.add(src)
    db_session.commit()

    problem = Problem(
        title="",
        source_type="pdf",
        source_pdf_id=source_pdf_id,
        page_number=1,
        problem_image_path=image_path,
    )
    db_session.add(problem)
    db_session.commit()
    db_session.refresh(problem)
    return problem


def _region_count(db_session, problem_id):
    return (
        db_session.query(ProblemRegion)
        .filter(ProblemRegion.problem_id == problem_id)
        .count()
    )


# ---------------------------------------------------------------------------
# Req 1.2 — 이미지 읽기 불가
# ---------------------------------------------------------------------------
def test_image_unreadable_returns_error_no_regions(db_session, tmp_path):
    missing = str(tmp_path / "missing.png")
    problem = _make_problem(db_session, missing)
    client = FakeVisionClient(raw_json=make_vision_success_json(), configured=True)
    service = ProblemRegionExtractionService(db_session, vision_client=client)

    result = service.extract_regions(problem)

    assert result.success is False
    assert result.failure_type == "image_unreadable"
    assert result.region_count == 0
    # 이미지 검증이 먼저 실패하므로 Vision 호출조차 없다.
    assert client.call_count == 0
    assert _region_count(db_session, problem.id) == 0


# ---------------------------------------------------------------------------
# Req 6.1, 6.4 — 자격증명 폴백 + warning 로그 1회
# ---------------------------------------------------------------------------
def test_credential_fallback_success_with_warning(db_session, tmp_path, caplog):
    image_path = _write_image(tmp_path)
    problem = _make_problem(db_session, image_path)
    client = FakeVisionClient(configured=False)
    service = ProblemRegionExtractionService(db_session, vision_client=client)

    with caplog.at_level(logging.WARNING):
        result = service.extract_regions(problem)

    assert result.success is True
    assert result.fallback_used is True
    assert result.region_count == 0
    # 폴백 경로에서는 Vision extract 를 호출하지 않는다.
    assert client.call_count == 0
    # warning 로그가 정확히 1회.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


# ---------------------------------------------------------------------------
# Req 14.5 — malformed 부분 저장 없음
# ---------------------------------------------------------------------------
def test_malformed_persists_nothing(db_session, tmp_path):
    image_path = _write_image(tmp_path)
    problem = _make_problem(db_session, image_path)
    # 'regions' 리스트가 없는 dict → 서비스의 구조 검증이 malformed로 판정.
    client = FakeVisionClient(raw_json=make_vision_malformed(), configured=True)
    service = ProblemRegionExtractionService(db_session, vision_client=client)

    result = service.extract_regions(problem)

    assert result.success is False
    assert result.failure_type == "malformed"
    assert _region_count(db_session, problem.id) == 0


# ---------------------------------------------------------------------------
# Req 11.6 — 빈 영역 → 성공 + 빈 조립 캐시
# ---------------------------------------------------------------------------
def test_empty_regions_success_empty_cache(db_session, tmp_path):
    image_path = _write_image(tmp_path)
    problem = _make_problem(db_session, image_path)
    client = FakeVisionClient(raw_json=make_vision_empty(), configured=True)
    service = ProblemRegionExtractionService(db_session, vision_client=client)

    result = service.extract_regions(problem)

    assert result.success is True
    assert result.region_count == 0
    db_session.refresh(problem)
    assert problem.raw_text == ""
    assert problem.raw_ocr_text == ""
    assert problem.latex_text == ""


# ---------------------------------------------------------------------------
# Req 5.5 — 지문 OCR 실패 시 미저장
# ---------------------------------------------------------------------------
def test_passage_ocr_failure_no_persist(db_session, tmp_path):
    image_path = _write_image(tmp_path)
    problem = _make_problem(db_session, image_path)
    # passage 객체가 있지만 ocr_text 가 비어 있어 신규 Passage 생성이 실패해야 한다.
    raw_json = {
        "regions": [
            {
                "region_type": "QUESTION_TEXT",
                "bounding_box": {"left": 0, "top": 0, "right": 50, "bottom": 50},
                "ocr_text": "문제 텍스트",
                "latex_text": "문제 텍스트",
                "confidence": 0.9,
            }
        ],
        "passage": {
            "crop_box": {"left": 0, "top": 0, "right": 100, "bottom": 40},
            "image_path": "uploads/passage.png",
            "ocr_text": "",  # 빈 OCR → 실패(Req 5.5)
            "latex_text": None,
        },
    }
    client = FakeVisionClient(raw_json=raw_json, configured=True)
    service = ProblemRegionExtractionService(db_session, vision_client=client)

    result = service.extract_regions(problem)

    assert result.success is False
    assert result.failure_type == "passage_ocr_failed"
    # 부분 저장 없음: 영역도 아직 영속화되지 않았고 passage_id 미설정.
    assert _region_count(db_session, problem.id) == 0
    db_session.refresh(problem)
    assert problem.passage_id is None

"""Task 11.2: PDF 임포트 파이프라인의 영역 추출 실패 격리 테스트.

_Requirements: 7.3, 7.4_

한 문제 이미지의 영역 추출이 예외로 실패해도 전체 임포트 파이프라인이 중단되지
않고(Req 7.4), 실패한 문제만 status="failed"로 표시되며(Req 7.3) 나머지 문제는
계속 처리되는지 검증한다.

자격증명이 없으면 실제 extract_regions는 스텁 폴백으로 성공을 반환하므로(Req 6.1),
except 경로를 강제로 타게 하려면 extract_regions가 항상 예외를 던지도록
monkeypatch 해야 한다. 그렇게 해도 import_pdf가 완주하는지가 이 테스트의 핵심이다.
"""

import importlib
from pathlib import Path

from fastapi.testclient import TestClient

from app.models.problem import Problem


def create_test_pdf(path: Path) -> None:
    """감지 가능한 한국어 문제 텍스트가 담긴 소형 테스트 PDF를 만든다.

    (tests/test_pdf_import_flow.py의 헬퍼를 그대로 복제한 것)
    """
    try:
        import fitz
    except ModuleNotFoundError:
        fitz = None

    if fitz is None:
        path.write_bytes(b"%PDF-1.4\n%test")
        return

    doc = fitz.open()
    page = doc.new_page()

    page.insert_text((72, 72), "Sample Problem 1", fontsize=12)
    page.insert_text((72, 120), "1.", fontsize=11)
    page.insert_text((72, 140), "함수의 최댓값을 구하시오.", fontsize=10, fontname="korea")
    page.insert_text((72, 200), "2.", fontsize=11)
    page.insert_text((72, 220), "확률은 얼마인지 옳은 것을 구하시오.", fontsize=10, fontname="korea")
    page.insert_text((400, 120), "3.", fontsize=11)
    page.insert_text((400, 140), "넓이의 값은 최솟값이다 구하시오.", fontsize=10, fontname="korea")

    doc.save(path)
    doc.close()


def test_region_extraction_failure_does_not_abort_import(tmp_path, monkeypatch):
    """extract_regions가 항상 예외를 던져도 임포트는 완주하고, 각 문제는 failed다."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("UPLOADS_ROOT", str(tmp_path / "uploads"))

    import app.core.database as database_module

    importlib.reload(database_module)
    from app.core.database import SessionLocal, create_tables

    # reload가 엔진을 리셋하므로 새 임시 DB에 테이블을 생성한다.
    create_tables()

    import app.main as main_module

    importlib.reload(main_module)

    # 모든 영역 추출을 강제로 실패(예외)시켜 파이프라인의 except 격리 경로를 탄다.
    import app.services.problem_region_extraction_service as extraction_module

    def _always_raise(self, problem):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        extraction_module.ProblemRegionExtractionService,
        "extract_regions",
        _always_raise,
    )

    client = TestClient(main_module.app)
    pdf_path = tmp_path / "sample.pdf"
    create_test_pdf(pdf_path)

    with pdf_path.open("rb") as file_obj:
        response = client.post(
            "/api/pdf-import/upload",
            files={"file": ("sample.pdf", file_obj, "application/pdf")},
        )

    # 파이프라인이 예외로 중단되지 않고 정상 완료되어야 한다 (Req 7.4).
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "imported"
    assert payload["imported_problem_count"] > 0

    # 생성된 모든 문제가 처리되었고, 추출이 실패했으므로 전부 failed 상태여야 한다 (Req 7.3).
    db = SessionLocal()
    try:
        problems = (
            db.query(Problem)
            .filter(Problem.source_pdf_id == payload["source_pdf_id"])
            .all()
        )
        assert len(problems) == payload["imported_problem_count"]
        assert len(problems) > 0
        for problem in problems:
            assert problem.status == "failed"
    finally:
        db.close()

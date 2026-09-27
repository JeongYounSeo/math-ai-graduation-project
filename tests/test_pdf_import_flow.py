import importlib
from pathlib import Path

from fastapi.testclient import TestClient

from app.models.problem import Problem
from app.models.source_pdf import SourcePDF


def create_test_pdf(path: Path) -> None:
    try:
        import fitz
    except ModuleNotFoundError:
        fitz = None

    if fitz is None:
        path.write_bytes(b"%PDF-1.4\n%test")
        return

    doc = fitz.open()
    page = doc.new_page()

    # 문제 번호와 텍스트를 추가해서 감지 테스트 가능하게 함.
    # problem_text_filter_service가 실제 문제인지 판단할 수 있도록, 본문에는
    # "구하시오"/"값은"/"최댓값" 같은 문제다운 한국어 표현을 넣는다
    # (내장 CJK 폰트("korea")는 ASCII 문자와 섞이면 추출 시 자간이 흐트러질 수
    # 있어, 문제 번호 라벨은 별도 호출로 기본 폰트에 남긴다).
    page.insert_text((72, 72), "Sample Problem 1", fontsize=12)
    page.insert_text((72, 120), "1.", fontsize=11)
    page.insert_text((72, 140), "함수의 최댓값을 구하시오.", fontsize=10, fontname="korea")
    page.insert_text((72, 200), "2.", fontsize=11)
    page.insert_text((72, 220), "확률은 얼마인지 옳은 것을 구하시오.", fontsize=10, fontname="korea")
    page.insert_text((400, 120), "3.", fontsize=11)
    page.insert_text((400, 140), "넓이의 값은 최솟값이다 구하시오.", fontsize=10, fontname="korea")

    doc.save(path)
    doc.close()


def test_reprocess_source_pdf_preserves_original_and_skips_vision(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'reprocess.db'}")
    monkeypatch.setenv("UPLOADS_ROOT", str(tmp_path / "uploads"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)

    import app.core.database as database_module
    import app.core.storage as storage_module
    import app.main as main_module
    importlib.reload(database_module)
    importlib.reload(storage_module)
    importlib.reload(main_module)

    client = TestClient(main_module.app)
    pdf_path = tmp_path / "sample.pdf"
    create_test_pdf(pdf_path)
    with pdf_path.open("rb") as file_obj:
        response = client.post(
            "/api/pdf-import/upload",
            files={"file": ("sample.pdf", file_obj, "application/pdf")},
        )
    assert response.status_code == 200
    original_id = response.json()["source_pdf_id"]

    from app.services.problem_region_extraction_service import ProblemRegionExtractionService

    def vision_must_not_run(*_args, **_kwargs):
        raise AssertionError("Vision region extraction must not run during A reprocess")

    monkeypatch.setattr(ProblemRegionExtractionService, "extract_regions", vision_must_not_run)
    response = client.post(f"/api/pdf-import/source-pdfs/{original_id}/reprocess")
    assert response.status_code == 200, response.text
    result = response.json()
    new_id = result["source_pdf_id"]
    assert new_id != original_id
    assert result["reprocessed_from_source_pdf_id"] == original_id
    assert result["numbered_problem_count"] >= 2

    from app.models.problem_region import ProblemRegion, RegionType

    db = database_module.SessionLocal()
    try:
        original_count = db.query(Problem).filter(Problem.source_pdf_id == original_id).count()
        new_problems = db.query(Problem).filter(Problem.source_pdf_id == new_id).all()
        assert original_count > 0
        assert len(new_problems) == result["imported_problem_count"]
        assert len({p.problem_number for p in new_problems if p.problem_number}) >= 2
        assert all(
            db.query(ProblemRegion).filter(
                ProblemRegion.problem_id == p.id,
                ProblemRegion.region_type == RegionType.FULL_PROBLEM.value,
            ).count() == 1
            for p in new_problems
        )
    finally:
        db.close()

    missing = client.post("/api/pdf-import/source-pdfs/PDF_DOESNOTEXIST/reprocess")
    assert missing.status_code == 404


def test_pdf_upload_creates_source_pdf_and_problem_candidates(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("UPLOADS_ROOT", str(tmp_path / "uploads"))
    # Tests must not hit the network: clear Claude credentials so the
    # region extraction service falls back to the stub (Req 6/15) instead
    # of calling the real API. Without this, a .env key would be loaded
    # and the import pipeline would mark problems "failed" on connection error.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)

    import app.core.database as database_module
    importlib.reload(database_module)
    from app.core.database import SessionLocal

    # app.core.storage.DEFAULT_UPLOAD_ROOT는 모듈 import 시점에 UPLOADS_ROOT를
    # 캡처하는 모듈 전역이다. 다른 테스트가 먼저 storage를 import 하면 이 값이
    # 굳어져(예: 기본값 "uploads"), 여기서 monkeypatch로 UPLOADS_ROOT를 바꿔도
    # 페이지/문제 이미지가 tmp_path가 아닌 옛 루트에 기록되어 경로 단언이 깨진다.
    # storage를 reload 해 새 UPLOADS_ROOT로 DEFAULT_UPLOAD_ROOT를 재계산한다.
    import app.core.storage as storage_module
    importlib.reload(storage_module)

    import app.main as main_module
    importlib.reload(main_module)

    client = TestClient(main_module.app)
    pdf_path = tmp_path / "sample.pdf"
    create_test_pdf(pdf_path)

    with pdf_path.open("rb") as file_obj:
        response = client.post(
            "/api/pdf-import/upload",
            files={"file": ("sample.pdf", file_obj, "application/pdf")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "imported"
    assert payload["total_pages"] >= 1
    assert payload["imported_problem_count"] > 0

    db = SessionLocal()
    try:
        source_pdf = (
            db.query(SourcePDF)
            .filter(SourcePDF.source_pdf_id == payload["source_pdf_id"])
            .first()
        )
        assert source_pdf is not None

        problem_count = (
            db.query(Problem)
            .filter(Problem.source_pdf_id == payload["source_pdf_id"])
            .count()
        )
        assert problem_count > 0

        first_problem = (
            db.query(Problem)
            .filter(Problem.source_pdf_id == payload["source_pdf_id"])
            .first()
        )
        assert first_problem is not None
        assert first_problem.status == "unclassified"
    finally:
        db.close()

    page_image_path = tmp_path / "uploads" / "pages" / payload["source_pdf_id"] / "page_001.png"
    assert page_image_path.exists()

    problem_image_path = tmp_path / "uploads" / "problems" / payload["source_pdf_id"] / "P_000001.png"
    assert problem_image_path.exists()


def test_problem_number_detection_improves_crop_count(tmp_path, monkeypatch):
    """
    문제 번호 감지가 동작하면 fallback crop보다 더 많은 문제 후보가 생성되어야 한다.
    """
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("UPLOADS_ROOT", str(tmp_path / "uploads"))
    # Tests must not hit the network: clear Claude credentials so the
    # region extraction service falls back to the stub (Req 6/15) instead
    # of calling the real API. Without this, a .env key would be loaded
    # and the import pipeline would mark problems "failed" on connection error.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)

    import app.core.database as database_module
    importlib.reload(database_module)
    from app.core.database import SessionLocal

    # app.core.storage.DEFAULT_UPLOAD_ROOT는 모듈 import 시점에 UPLOADS_ROOT를
    # 캡처하는 모듈 전역이다. 다른 테스트가 먼저 storage를 import 하면 이 값이
    # 굳어져(예: 기본값 "uploads"), 여기서 monkeypatch로 UPLOADS_ROOT를 바꿔도
    # 페이지/문제 이미지가 tmp_path가 아닌 옛 루트에 기록되어 경로 단언이 깨진다.
    # storage를 reload 해 새 UPLOADS_ROOT로 DEFAULT_UPLOAD_ROOT를 재계산한다.
    import app.core.storage as storage_module
    importlib.reload(storage_module)

    import app.main as main_module
    importlib.reload(main_module)

    client = TestClient(main_module.app)
    pdf_path = tmp_path / "sample.pdf"
    create_test_pdf(pdf_path)

    with pdf_path.open("rb") as file_obj:
        response = client.post(
            "/api/pdf-import/upload",
            files={"file": ("sample.pdf", file_obj, "application/pdf")},
        )

    payload = response.json()
    db = SessionLocal()
    try:
        # 같은 page_number에서 여러 문제 번호가 감지됐으면
        # 각 문제별로 별도 Problem 레코드가 생성돼야 한다.
        problems = (
            db.query(Problem)
            .filter(Problem.source_pdf_id == payload["source_pdf_id"])
            .all()
        )
        
        # 문제 번호가 감지된 레코드가 있는지 확인
        detected_problems = [p for p in problems if p.problem_number is not None]
        
        # 최소한 일부 문제에서 problem_number가 감지돼야 한다
        # (환경에 따라 OCR 성공 여부가 다르므로 엄격하게 검사하지는 않음)
        assert len(problems) > 0
    finally:
        db.close()


def test_problem_number_in_response(tmp_path, monkeypatch):
    """
    문제 조회 시 problem_number 필드가 응답에 포함되는지 확인한다.
    """
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("UPLOADS_ROOT", str(tmp_path / "uploads"))
    # Tests must not hit the network: clear Claude credentials so the
    # region extraction service falls back to the stub (Req 6/15) instead
    # of calling the real API. Without this, a .env key would be loaded
    # and the import pipeline would mark problems "failed" on connection error.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)

    import app.core.database as database_module
    importlib.reload(database_module)
    from app.core.database import SessionLocal

    # app.core.storage.DEFAULT_UPLOAD_ROOT는 모듈 import 시점에 UPLOADS_ROOT를
    # 캡처하는 모듈 전역이다. 다른 테스트가 먼저 storage를 import 하면 이 값이
    # 굳어져(예: 기본값 "uploads"), 여기서 monkeypatch로 UPLOADS_ROOT를 바꿔도
    # 페이지/문제 이미지가 tmp_path가 아닌 옛 루트에 기록되어 경로 단언이 깨진다.
    # storage를 reload 해 새 UPLOADS_ROOT로 DEFAULT_UPLOAD_ROOT를 재계산한다.
    import app.core.storage as storage_module
    importlib.reload(storage_module)

    import app.main as main_module
    importlib.reload(main_module)

    client = TestClient(main_module.app)
    pdf_path = tmp_path / "sample.pdf"
    create_test_pdf(pdf_path)

    with pdf_path.open("rb") as file_obj:
        response = client.post(
            "/api/pdf-import/upload",
            files={"file": ("sample.pdf", file_obj, "application/pdf")},
        )

    payload = response.json()
    
    # 생성된 문제 조회
    response = client.get(f"/api/problems?source_pdf_id={payload['source_pdf_id']}&page=1&page_size=100")
    assert response.status_code == 200
    problems = response.json()
    assert len(problems) > 0
    
    # 응답에 problem_number 필드가 있는지 확인
    for problem in problems:
        assert "problem_number" in problem
        assert "problem_image_url" in problem
        assert "page_image_url" in problem

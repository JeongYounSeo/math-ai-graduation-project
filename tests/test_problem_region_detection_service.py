import importlib
from pathlib import Path

import pytest
from PIL import Image


def _fresh_db_session(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("UPLOADS_ROOT", str(tmp_path / "uploads"))

    import app.core.database as database_module

    importlib.reload(database_module)
    database_module.create_tables()

    import app.core.storage as storage_module

    monkeypatch.setattr(storage_module, "DEFAULT_UPLOAD_ROOT", tmp_path / "uploads")

    return database_module.SessionLocal()


def _make_image(path: Path, size=(200, 100)) -> Path:
    Image.new("RGB", size, "white").save(path)
    return path


@pytest.mark.asyncio
async def test_detect_and_save_regions_creates_child_regions_and_crops(tmp_path, monkeypatch):
    db = _fresh_db_session(tmp_path, monkeypatch)

    from app.models.problem import Problem
    from app.repositories.problem_region_repository import ProblemRegionRepository
    from app.services.region_detectors.base import DetectedRegion
    from app.services.region_detectors.mock import MockRegionDetector
    from app.services.problem_region_detection_service import ProblemRegionDetectionService

    image_path = _make_image(tmp_path / "problem.png")
    problem = Problem(title="", source_type="pdf", problem_image_path=str(image_path))
    db.add(problem)
    db.commit()
    db.refresh(problem)

    full_problem = ProblemRegionRepository(db).create_full_problem_region_from_problem(problem)

    fixed_regions = [
        DetectedRegion(region_type="figure", x1=10, y1=10, x2=60, y2=60, confidence=0.8, reason="그림으로 보임"),
        DetectedRegion(region_type="table", x1=70, y1=10, x2=190, y2=90, confidence=0.7, reason="표로 보임"),
    ]
    detector = MockRegionDetector(regions=fixed_regions)
    service = ProblemRegionDetectionService(db, detector)

    created = await service.detect_and_save_regions(problem.id)

    assert len(created) == 2
    assert [r.region_type for r in created] == ["figure", "table"]
    for region in created:
        assert region.parent_region_id == full_problem.id
        assert region.provider == "mock-region-detector"
        assert region.cropped_image_path
        assert Path(region.cropped_image_path).exists()
    assert created[0].label == "그림으로 보임"

    db.close()


@pytest.mark.asyncio
async def test_detect_and_save_regions_raises_for_missing_problem(tmp_path, monkeypatch):
    db = _fresh_db_session(tmp_path, monkeypatch)

    from app.services.region_detectors.mock import MockRegionDetector
    from app.services.problem_region_detection_service import ProblemRegionDetectionService

    service = ProblemRegionDetectionService(db, MockRegionDetector())

    with pytest.raises(ValueError):
        await service.detect_and_save_regions(9999)

    db.close()


@pytest.mark.asyncio
async def test_detect_and_save_regions_raises_without_image(tmp_path, monkeypatch):
    db = _fresh_db_session(tmp_path, monkeypatch)

    from app.models.problem import Problem
    from app.services.region_detectors.mock import MockRegionDetector
    from app.services.problem_region_detection_service import ProblemRegionDetectionService

    problem = Problem(title="", source_type="pdf")
    db.add(problem)
    db.commit()
    db.refresh(problem)

    service = ProblemRegionDetectionService(db, MockRegionDetector())

    with pytest.raises(ValueError):
        await service.detect_and_save_regions(problem.id)

    db.close()

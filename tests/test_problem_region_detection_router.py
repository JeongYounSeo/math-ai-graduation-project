import importlib
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image


def _make_image(path: Path, size=(200, 100)) -> Path:
    Image.new("RGB", size, "white").save(path)
    return path


def _fresh_client(tmp_path, monkeypatch, region_detector_factory):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("UPLOADS_ROOT", str(tmp_path / "uploads"))

    import app.core.database as database_module

    importlib.reload(database_module)

    import app.main as main_module

    importlib.reload(main_module)

    import app.core.storage as storage_module

    monkeypatch.setattr(storage_module, "DEFAULT_UPLOAD_ROOT", tmp_path / "uploads")

    from app.services.problem_region_detection_service import get_region_detector

    main_module.app.dependency_overrides[get_region_detector] = region_detector_factory

    return TestClient(main_module.app)


def _create_problem(client: TestClient, **overrides) -> int:
    payload = {"title": "테스트 문제"}
    payload.update(overrides)
    response = client.post("/problems/", json=payload)
    assert response.status_code == 200
    return response.json()["id"]


def test_detect_endpoint_creates_and_crops_regions(tmp_path, monkeypatch):
    from app.services.region_detectors.base import DetectedRegion
    from app.services.region_detectors.mock import MockRegionDetector

    fixed_regions = [
        DetectedRegion(region_type="figure", x1=10, y1=10, x2=60, y2=60, confidence=0.8, reason="그림"),
    ]
    client = _fresh_client(tmp_path, monkeypatch, lambda: MockRegionDetector(regions=fixed_regions))

    image_path = _make_image(tmp_path / "problem.png")
    problem_id = _create_problem(client, problem_image_path=str(image_path))

    resp = client.post(f"/api/problems/{problem_id}/regions/detect")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["region_type"] == "figure"
    assert body[0]["cropped_image_path"]
    assert Path(body[0]["cropped_image_path"]).exists()

    regions = client.get(f"/api/problems/{problem_id}/regions").json()
    figure_regions = [r for r in regions if r["region_type"] == "figure"]
    assert len(figure_regions) == 1


def test_detect_endpoint_missing_problem_returns_404(tmp_path, monkeypatch):
    from app.services.region_detectors.mock import MockRegionDetector

    client = _fresh_client(tmp_path, monkeypatch, lambda: MockRegionDetector())

    resp = client.post("/api/problems/9999/regions/detect")
    assert resp.status_code == 404


def test_detect_endpoint_without_image_returns_400(tmp_path, monkeypatch):
    from app.services.region_detectors.mock import MockRegionDetector

    client = _fresh_client(tmp_path, monkeypatch, lambda: MockRegionDetector())
    problem_id = _create_problem(client)

    resp = client.post(f"/api/problems/{problem_id}/regions/detect")
    assert resp.status_code == 400


def test_detect_endpoint_detector_failure_returns_500(tmp_path, monkeypatch):
    from app.services.region_detectors.base import RegionDetector

    class FailingDetector(RegionDetector):
        async def detect(self, image_path: str):
            raise RuntimeError("boom")

    client = _fresh_client(tmp_path, monkeypatch, lambda: FailingDetector())

    image_path = _make_image(tmp_path / "problem.png")
    problem_id = _create_problem(client, problem_image_path=str(image_path))

    resp = client.post(f"/api/problems/{problem_id}/regions/detect")
    assert resp.status_code == 500

import importlib
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image


def _make_image(path: Path, size=(400, 300)) -> Path:
    Image.new("RGB", size, "white").save(path)
    return path


def _fresh_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("UPLOADS_ROOT", str(tmp_path / "uploads"))

    import app.core.database as database_module

    importlib.reload(database_module)

    import app.main as main_module

    importlib.reload(main_module)

    import app.core.storage as storage_module

    monkeypatch.setattr(storage_module, "DEFAULT_UPLOAD_ROOT", tmp_path / "uploads")

    return TestClient(main_module.app)


def _create_problem(client: TestClient, **overrides) -> int:
    payload = {"title": "테스트 문제"}
    payload.update(overrides)
    response = client.post("/problems/", json=payload)
    assert response.status_code == 200
    return response.json()["id"]


def test_explicit_crop_endpoint_creates_file(tmp_path, monkeypatch):
    client = _fresh_client(tmp_path, monkeypatch)

    image_path = _make_image(tmp_path / "problem.png")
    problem_id = _create_problem(client, problem_image_path=str(image_path))

    create_resp = client.post(
        f"/api/problems/{problem_id}/regions",
        json={"problem_id": problem_id, "region_type": "figure", "x1": 10, "y1": 10, "x2": 60, "y2": 60},
    )
    assert create_resp.status_code == 200
    region_id = create_resp.json()["id"]

    crop_resp = client.post(f"/api/problem-regions/{region_id}/crop")
    assert crop_resp.status_code == 200
    cropped_image_path = crop_resp.json()["cropped_image_path"]
    assert cropped_image_path
    assert Path(cropped_image_path).exists()


def test_create_region_with_coords_autocrops(tmp_path, monkeypatch):
    client = _fresh_client(tmp_path, monkeypatch)

    image_path = _make_image(tmp_path / "problem.png")
    problem_id = _create_problem(client, problem_image_path=str(image_path))

    create_resp = client.post(
        f"/api/problems/{problem_id}/regions",
        json={"problem_id": problem_id, "region_type": "graph", "x1": 5, "y1": 5, "x2": 55, "y2": 55},
    )
    assert create_resp.status_code == 200
    body = create_resp.json()
    assert body["cropped_image_path"]
    assert Path(body["cropped_image_path"]).exists()


def test_create_region_without_coords_does_not_autocrop(tmp_path, monkeypatch):
    client = _fresh_client(tmp_path, monkeypatch)

    problem_id = _create_problem(client)

    create_resp = client.post(
        f"/api/problems/{problem_id}/regions",
        json={"problem_id": problem_id, "region_type": "choice_option"},
    )
    assert create_resp.status_code == 200
    assert create_resp.json()["cropped_image_path"] is None


def test_update_region_with_coords_autocrops(tmp_path, monkeypatch):
    client = _fresh_client(tmp_path, monkeypatch)

    image_path = _make_image(tmp_path / "problem.png")
    problem_id = _create_problem(client, problem_image_path=str(image_path))

    create_resp = client.post(
        f"/api/problems/{problem_id}/regions",
        json={"problem_id": problem_id, "region_type": "table"},
    )
    region_id = create_resp.json()["id"]
    assert create_resp.json()["cropped_image_path"] is None

    patch_resp = client.patch(
        f"/api/problem-regions/{region_id}",
        json={"x1": 0, "y1": 0, "x2": 40, "y2": 40},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["cropped_image_path"]
    assert Path(patch_resp.json()["cropped_image_path"]).exists()


def test_crop_endpoint_without_coords_returns_400(tmp_path, monkeypatch):
    client = _fresh_client(tmp_path, monkeypatch)

    problem_id = _create_problem(client)
    create_resp = client.post(
        f"/api/problems/{problem_id}/regions",
        json={"problem_id": problem_id, "region_type": "choice_option"},
    )
    region_id = create_resp.json()["id"]

    crop_resp = client.post(f"/api/problem-regions/{region_id}/crop")
    assert crop_resp.status_code == 400


def test_crop_endpoint_missing_region_returns_404(tmp_path, monkeypatch):
    client = _fresh_client(tmp_path, monkeypatch)

    crop_resp = client.post("/api/problem-regions/9999/crop")
    assert crop_resp.status_code == 404

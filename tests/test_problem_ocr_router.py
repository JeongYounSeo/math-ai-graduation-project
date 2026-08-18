import importlib
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image


def _make_image(path: Path) -> Path:
    Image.new("RGB", (100, 100), "white").save(path)
    return path


def _fresh_client(tmp_path, monkeypatch, ocr_provider_factory):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("UPLOADS_ROOT", str(tmp_path / "uploads"))

    import app.core.database as database_module

    importlib.reload(database_module)

    import app.main as main_module

    importlib.reload(main_module)

    from app.services.problem_ocr_service import get_ocr_provider

    main_module.app.dependency_overrides[get_ocr_provider] = ocr_provider_factory

    return TestClient(main_module.app)


def _create_problem(client: TestClient, **overrides) -> int:
    payload = {"title": "테스트 문제"}
    payload.update(overrides)
    response = client.post("/problems/", json=payload)
    assert response.status_code == 200
    return response.json()["id"]


def test_run_ocr_updates_problem_choices_and_full_problem_region(tmp_path, monkeypatch):
    from app.services.ocr_providers.mock import MockOCRProvider

    client = _fresh_client(
        tmp_path,
        monkeypatch,
        lambda: MockOCRProvider(
            body_text="문제 본문 텍스트",
            choices=["13/2", "27/4", "7", "29/4", "15/2"],
            latex_text="x^2",
            confidence=0.92,
        ),
    )

    image_path = _make_image(tmp_path / "problem.png")
    problem_id = _create_problem(client, problem_image_path=str(image_path))

    resp = client.post(f"/problems/{problem_id}/ocr")
    assert resp.status_code == 200
    body = resp.json()
    assert body["problem_id"] == problem_id
    assert body["body_text"] == "문제 본문 텍스트"
    assert body["choices"] == ["13/2", "27/4", "7", "29/4", "15/2"]
    assert body["provider"] == "mock"
    assert body["confidence"] == 0.92

    problem = client.get(f"/api/problems/{problem_id}").json()
    assert problem["raw_ocr_text"] == "문제 본문 텍스트"
    assert problem["latex_text"] == "x^2"

    choices = client.get(f"/api/problems/{problem_id}/choices").json()
    assert len(choices) == 5
    assert [c["choice_label"] for c in choices] == ["①", "②", "③", "④", "⑤"]
    assert all(c["is_correct"] is None for c in choices)

    regions = client.get(f"/api/problems/{problem_id}/regions").json()
    full_problem_regions = [r for r in regions if r["region_type"] == "full_problem"]
    assert len(full_problem_regions) == 1
    assert full_problem_regions[0]["extracted_text"] == "문제 본문 텍스트"
    assert full_problem_regions[0]["latex_text"] == "x^2"
    assert full_problem_regions[0]["provider"] == "mock"


def test_run_ocr_without_choices_leaves_choices_empty(tmp_path, monkeypatch):
    from app.services.ocr_providers.mock import MockOCRProvider

    client = _fresh_client(
        tmp_path,
        monkeypatch,
        lambda: MockOCRProvider(body_text="주관식 문제 본문", choices=[]),
    )

    image_path = _make_image(tmp_path / "problem.png")
    problem_id = _create_problem(client, problem_image_path=str(image_path))

    resp = client.post(f"/problems/{problem_id}/ocr")
    assert resp.status_code == 200
    assert resp.json()["choices"] == []

    choices = client.get(f"/api/problems/{problem_id}/choices").json()
    assert choices == []


def test_run_ocr_without_image_returns_400(tmp_path, monkeypatch):
    from app.services.ocr_providers.mock import MockOCRProvider

    client = _fresh_client(tmp_path, monkeypatch, lambda: MockOCRProvider())
    problem_id = _create_problem(client)

    resp = client.post(f"/problems/{problem_id}/ocr")
    assert resp.status_code == 400


def test_run_ocr_missing_problem_returns_404(tmp_path, monkeypatch):
    from app.services.ocr_providers.mock import MockOCRProvider

    client = _fresh_client(tmp_path, monkeypatch, lambda: MockOCRProvider())

    resp = client.post("/problems/9999/ocr")
    assert resp.status_code == 404


def test_run_ocr_provider_failure_returns_500(tmp_path, monkeypatch):
    from app.services.ocr_providers.mock import MockOCRProvider

    client = _fresh_client(tmp_path, monkeypatch, lambda: MockOCRProvider())

    missing_image_path = str(tmp_path / "missing.png")
    problem_id = _create_problem(client, problem_image_path=missing_image_path)

    resp = client.post(f"/problems/{problem_id}/ocr")
    assert resp.status_code == 500

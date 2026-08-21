import importlib

from fastapi.testclient import TestClient


def _fresh_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("UPLOADS_ROOT", str(tmp_path / "uploads"))

    import app.core.database as database_module

    importlib.reload(database_module)

    import app.main as main_module

    importlib.reload(main_module)
    return TestClient(main_module.app)


def _create_problem(client: TestClient) -> int:
    response = client.post("/problems/", json={"title": "테스트 문제"})
    assert response.status_code == 200
    return response.json()["id"]


def test_create_and_get_regions(tmp_path, monkeypatch):
    client = _fresh_client(tmp_path, monkeypatch)
    problem_id = _create_problem(client)

    create_resp = client.post(
        f"/api/problems/{problem_id}/regions",
        json={"problem_id": problem_id, "region_type": "figure", "label": "그림"},
    )
    assert create_resp.status_code == 200
    region_id = create_resp.json()["id"]

    list_resp = client.get(f"/api/problems/{problem_id}/regions")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1
    assert list_resp.json()[0]["id"] == region_id


def test_create_region_rejects_mismatched_problem_id(tmp_path, monkeypatch):
    client = _fresh_client(tmp_path, monkeypatch)
    problem_id = _create_problem(client)

    resp = client.post(
        f"/api/problems/{problem_id}/regions",
        json={"problem_id": problem_id + 999, "region_type": "figure"},
    )
    assert resp.status_code == 400


def test_update_and_delete_region(tmp_path, monkeypatch):
    client = _fresh_client(tmp_path, monkeypatch)
    problem_id = _create_problem(client)

    create_resp = client.post(
        f"/api/problems/{problem_id}/regions",
        json={"problem_id": problem_id, "region_type": "figure", "label": "그림"},
    )
    region_id = create_resp.json()["id"]

    patch_resp = client.patch(f"/api/problem-regions/{region_id}", json={"label": "수정됨"})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["label"] == "수정됨"

    delete_resp = client.delete(f"/api/problem-regions/{region_id}")
    assert delete_resp.status_code == 200

    missing_resp = client.patch(f"/api/problem-regions/{region_id}", json={"label": "다시 수정"})
    assert missing_resp.status_code == 404

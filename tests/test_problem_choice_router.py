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


def test_replace_choices_endpoint(tmp_path, monkeypatch):
    client = _fresh_client(tmp_path, monkeypatch)
    problem_id = _create_problem(client)

    resp = client.post(
        f"/api/problems/{problem_id}/choices/replace",
        json={"choices": ["13/2", "27/4", "7", "29/4", "15/2"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 5
    assert [c["choice_label"] for c in body] == ["①", "②", "③", "④", "⑤"]
    assert all(c["is_correct"] is None for c in body)

    list_resp = client.get(f"/api/problems/{problem_id}/choices")
    assert len(list_resp.json()) == 5


def test_update_and_delete_choice(tmp_path, monkeypatch):
    client = _fresh_client(tmp_path, monkeypatch)
    problem_id = _create_problem(client)

    replace_resp = client.post(
        f"/api/problems/{problem_id}/choices/replace",
        json={"choices": ["13/2"]},
    )
    choice_id = replace_resp.json()[0]["id"]

    patch_resp = client.patch(f"/api/problem-choices/{choice_id}", json={"is_correct": True})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["is_correct"] is True

    delete_resp = client.delete(f"/api/problem-choices/{choice_id}")
    assert delete_resp.status_code == 200

    missing_resp = client.patch(f"/api/problem-choices/{choice_id}", json={"is_correct": False})
    assert missing_resp.status_code == 404

"""ProblemChoice 라우터 테스트 (FastAPI TestClient, 설계 §6).

인메모리 SQLite 엔진 + dependency_overrides[get_db] 로 세션을 주입해 격리한다.
전체 앱(main.py)을 로드하지 않고, ProblemChoice 라우터만 마운트한 경량 FastAPI
앱을 구성해 다른 서브시스템/네트워크 의존을 배제한다.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db_base import Base
from app.core.database import get_db

# 전체 모델을 import 해 Base.metadata 에 등록한다.
import app.models.problem  # noqa: F401
import app.models.source_pdf  # noqa: F401
import app.models.concept_module  # noqa: F401
import app.models.solution_module  # noqa: F401
import app.models.type_combination  # noqa: F401
import app.models.generated_problem  # noqa: F401
import app.models.passage  # noqa: F401
import app.models.problem_region  # noqa: F401
import app.models.problem_region_item  # noqa: F401
import app.models.problem_choice  # noqa: F401

from app.routers import problem_choice_router


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app = FastAPI()
    app.include_router(problem_choice_router.router)
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    engine.dispose()


def test_get_choices_empty(client):
    resp = client.get("/api/problems/1/choices")
    assert resp.status_code == 200
    body = resp.json()
    assert body["problem_id"] == 1
    assert body["choices"] == []


def test_create_choice(client):
    resp = client.post(
        "/api/problems/2/choices",
        json={"choice_index": 1, "text": "보기1", "choice_label": "\u2460"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["problem_id"] == 2
    assert body["choice_index"] == 1
    assert body["text"] == "보기1"
    # 정답 추측 금지: 명시하지 않았으므로 null.
    assert body["is_correct"] is None


def test_replace_then_get(client):
    resp = client.post(
        "/api/problems/3/choices/replace",
        json={"choices": ["a", "b", "c", "d", "e"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["problem_id"] == 3
    assert [c["choice_index"] for c in body["choices"]] == [1, 2, 3, 4, 5]
    assert [c["choice_label"] for c in body["choices"]] == [
        "\u2460",
        "\u2461",
        "\u2462",
        "\u2463",
        "\u2464",
    ]
    assert all(c["is_correct"] is None for c in body["choices"])

    # GET 으로 다시 확인.
    get_resp = client.get("/api/problems/3/choices")
    assert get_resp.status_code == 200
    get_body = get_resp.json()
    assert [c["text"] for c in get_body["choices"]] == ["a", "b", "c", "d", "e"]


def test_replace_nonexistent_problem_ok(client):
    # 존재하지 않는 problem_id 라도 500 이 아니라 정상 동작.
    resp = client.post(
        "/api/problems/9999/choices/replace",
        json={"choices": ["x"]},
    )
    assert resp.status_code == 200
    assert len(resp.json()["choices"]) == 1


def test_patch_sets_is_correct(client):
    created = client.post(
        "/api/problems/4/choices",
        json={"choice_index": 1, "text": "정답 후보"},
    ).json()
    choice_id = created["id"]

    # 사용자가 명시적으로 정답 설정하는 것은 허용됨(추측 금지는 자동 설정 금지 의미).
    resp = client.patch(
        f"/api/problem-choices/{choice_id}",
        json={"is_correct": True, "normalized_text": "정답"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_correct"] is True
    assert body["normalized_text"] == "정답"


def test_patch_missing_returns_404(client):
    resp = client.patch(
        "/api/problem-choices/99999",
        json={"is_correct": True},
    )
    assert resp.status_code == 404


def test_delete_choice(client):
    created = client.post(
        "/api/problems/5/choices",
        json={"choice_index": 1, "text": "삭제 대상"},
    ).json()
    choice_id = created["id"]

    resp = client.delete(f"/api/problem-choices/{choice_id}")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": True}

    # 다시 조회하면 없음.
    assert client.get("/api/problems/5/choices").json()["choices"] == []


def test_delete_missing_returns_404(client):
    resp = client.delete("/api/problem-choices/88888")
    assert resp.status_code == 404

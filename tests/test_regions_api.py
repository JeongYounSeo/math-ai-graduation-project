"""Task 10.3: GET /api/problems/{problem_id}/regions 라우팅 예시/엣지 테스트.

_Requirements: 12.1, 12.4, 12.5_

DB 격리는 tests/test_pdf_import_flow.py 패턴을 그대로 따른다: 임시 SQLite로
DATABASE_URL을 지정한 뒤 database 모듈과 main 모듈을 reload 한다. reload가
엔진을 초기화하므로, 새 임시 DB에 테이블을 만들기 위해 create_tables()를 명시적으로
호출한다.
"""

import importlib

from fastapi.testclient import TestClient


def _bootstrap(tmp_path, monkeypatch):
    """임시 DB로 앱을 부팅하고 (client, SessionLocal)을 반환한다."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("UPLOADS_ROOT", str(tmp_path / "uploads"))

    import app.core.database as database_module

    importlib.reload(database_module)
    from app.core.database import SessionLocal, create_tables

    # reload가 엔진을 리셋하므로 새 임시 DB에 테이블을 생성해야 한다.
    create_tables()

    import app.main as main_module

    importlib.reload(main_module)

    client = TestClient(main_module.app)
    return client, SessionLocal


def _insert_problem(SessionLocal):
    """최소 필드로 Problem을 직접 삽입하고 id를 반환한다."""
    from app.models.problem import Problem

    db = SessionLocal()
    try:
        problem = Problem(title="", source_type="pdf", status="unclassified")
        db.add(problem)
        db.commit()
        db.refresh(problem)
        return problem.id
    finally:
        db.close()


def test_regions_endpoint_404_for_missing_problem(tmp_path, monkeypatch):
    """존재하지 않는 problem_id면 404를 반환한다 (Req 12.4)."""
    client, _ = _bootstrap(tmp_path, monkeypatch)

    response = client.get("/api/problems/999999/regions")

    assert response.status_code == 404


def test_regions_endpoint_empty_list_for_problem_without_regions(tmp_path, monkeypatch):
    """영역이 없는 기존 문제는 200과 빈 리스트를 반환한다 (Req 12.5)."""
    client, SessionLocal = _bootstrap(tmp_path, monkeypatch)
    problem_id = _insert_problem(SessionLocal)

    response = client.get(f"/api/problems/{problem_id}/regions")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {"problem_id": problem_id, "regions": []}


def test_regions_endpoint_returns_sorted_regions_with_items(tmp_path, monkeypatch):
    """영역은 order_index 오름차순으로, 항목은 중첩되어 반환된다 (Req 12.1, 12.2, 12.3)."""
    client, SessionLocal = _bootstrap(tmp_path, monkeypatch)
    problem_id = _insert_problem(SessionLocal)

    from app.models.problem_region import ProblemRegion
    from app.models.problem_region_item import ProblemRegionItem

    bbox = {"left": 0, "top": 0, "right": 10, "bottom": 10}

    db = SessionLocal()
    try:
        # 일부러 순서를 뒤섞어(order_index 2, 0, 1) 삽입한다.
        region2 = ProblemRegion(
            problem_id=problem_id,
            region_type="DIAGRAM",
            order_index=2,
            bounding_box=bbox,
            ocr_text=None,
            latex_text=None,
            image_path=None,
        )
        region0 = ProblemRegion(
            problem_id=problem_id,
            region_type="QUESTION_TEXT",
            order_index=0,
            bounding_box=bbox,
            ocr_text="문제 본문",
            latex_text="문제 본문",
            image_path=None,
        )
        region1 = ProblemRegion(
            problem_id=problem_id,
            region_type="CHOICE_BOX",
            order_index=1,
            bounding_box=bbox,
            ocr_text="선택지",
            latex_text="선택지",
            image_path=None,
        )
        db.add_all([region2, region0, region1])
        db.commit()
        db.refresh(region1)

        # CHOICE_BOX 영역에 라벨 항목을 순서를 뒤섞어(1, 0) 삽입한다.
        item1 = ProblemRegionItem(
            region_id=region1.id,
            label="②",
            order_index=1,
            text="두 번째",
        )
        item0 = ProblemRegionItem(
            region_id=region1.id,
            label="①",
            order_index=0,
            text="첫 번째",
        )
        db.add_all([item1, item0])
        db.commit()
        choice_region_id = region1.id
    finally:
        db.close()

    response = client.get(f"/api/problems/{problem_id}/regions")

    assert response.status_code == 200
    payload = response.json()
    assert payload["problem_id"] == problem_id

    regions = payload["regions"]
    assert len(regions) == 3

    # 영역이 order_index 오름차순(0, 1, 2)으로 정렬되었는지 확인 (Req 12.1).
    assert [r["order_index"] for r in regions] == [0, 1, 2]
    assert [r["region_type"] for r in regions] == [
        "QUESTION_TEXT",
        "CHOICE_BOX",
        "DIAGRAM",
    ]

    # 값이 없는 필드도 명시적 null 키로 존재해야 한다 (Req 12.2, 12.3).
    for region in regions:
        for key in ("region_type", "order_index", "ocr_text", "latex_text", "image_path"):
            assert key in region

    diagram_region = regions[2]
    assert diagram_region["region_type"] == "DIAGRAM"
    assert diagram_region["ocr_text"] is None
    assert diagram_region["latex_text"] is None
    assert diagram_region["image_path"] is None

    # CHOICE_BOX 영역의 items가 존재하고 item order_index 오름차순으로 정렬됐는지 확인.
    choice_region = next(r for r in regions if r["id"] == choice_region_id)
    items = choice_region["items"]
    assert len(items) == 2
    assert [i["order_index"] for i in items] == [0, 1]
    assert [i["label"] for i in items] == ["①", "②"]

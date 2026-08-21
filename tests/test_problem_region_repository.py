import importlib

import pytest


def _fresh_db_session(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")

    import app.core.database as database_module

    importlib.reload(database_module)
    database_module.create_tables()
    return database_module.SessionLocal()


@pytest.mark.asyncio
async def test_create_and_list_regions_by_problem(tmp_path, monkeypatch):
    db = _fresh_db_session(tmp_path, monkeypatch)
    from app.repositories.problem_region_repository import ProblemRegionRepository
    from app.schemas.problem_region_schema import ProblemRegionCreate

    repo = ProblemRegionRepository(db)

    await repo.create(ProblemRegionCreate(problem_id=1, region_type="full_problem", label="전체 문제", order_index=0))
    await repo.create(ProblemRegionCreate(problem_id=1, region_type="figure", label="그림", order_index=1))
    await repo.create(ProblemRegionCreate(problem_id=2, region_type="full_problem", label="다른 문제"))

    regions = await repo.list_by_problem(1)
    assert len(regions) == 2
    assert [r.region_type for r in regions] == ["full_problem", "figure"]

    db.close()


@pytest.mark.asyncio
async def test_list_by_problem_and_type_filters(tmp_path, monkeypatch):
    db = _fresh_db_session(tmp_path, monkeypatch)
    from app.repositories.problem_region_repository import ProblemRegionRepository
    from app.schemas.problem_region_schema import ProblemRegionCreate

    repo = ProblemRegionRepository(db)
    await repo.create(ProblemRegionCreate(problem_id=1, region_type="choice_option", label="①"))
    await repo.create(ProblemRegionCreate(problem_id=1, region_type="choice_option", label="②"))
    await repo.create(ProblemRegionCreate(problem_id=1, region_type="figure", label="그림"))

    options = await repo.list_by_problem_and_type(1, "choice_option")
    assert len(options) == 2

    db.close()


@pytest.mark.asyncio
async def test_update_and_delete_region(tmp_path, monkeypatch):
    db = _fresh_db_session(tmp_path, monkeypatch)
    from app.repositories.problem_region_repository import ProblemRegionRepository
    from app.schemas.problem_region_schema import ProblemRegionCreate, ProblemRegionUpdate

    repo = ProblemRegionRepository(db)
    region = await repo.create(ProblemRegionCreate(problem_id=1, region_type="figure", label="그림"))

    updated = await repo.update(region.id, ProblemRegionUpdate(label="수정된 그림"))
    assert updated.label == "수정된 그림"

    deleted = await repo.delete(region.id)
    assert deleted is True
    assert await repo.get(region.id) is None

    db.close()


@pytest.mark.asyncio
async def test_create_full_problem_region_from_problem_avoids_duplicates(tmp_path, monkeypatch):
    db = _fresh_db_session(tmp_path, monkeypatch)
    from app.models.problem import Problem
    from app.repositories.problem_region_repository import ProblemRegionRepository

    problem = Problem(
        title="",
        source_type="pdf",
        problem_image_path=str(tmp_path / "P_000001.png"),
        page_number=1,
        crop_box={"x": 10, "y": 20, "width": 100, "height": 50},
    )
    db.add(problem)
    db.commit()
    db.refresh(problem)

    repo = ProblemRegionRepository(db)
    first = repo.create_full_problem_region_from_problem(problem)
    assert first is not None
    assert first.region_type == "full_problem"
    assert first.x1 == 10
    assert first.y1 == 20
    assert first.x2 == 110
    assert first.y2 == 70

    # 중복 생성 방지: 두 번째 호출은 기존 region을 그대로 반환한다.
    second = repo.create_full_problem_region_from_problem(problem)
    assert second.id == first.id

    regions = await repo.list_by_problem(problem.id)
    assert len(regions) == 1

    db.close()

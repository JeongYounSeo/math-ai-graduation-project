import importlib

import pytest


@pytest.mark.asyncio
async def test_create_from_pdf_autocreates_full_problem_region(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")

    import app.core.database as database_module

    importlib.reload(database_module)
    database_module.create_tables()
    db = database_module.SessionLocal()

    from app.repositories.problem_repository import ProblemRepository
    from app.repositories.problem_region_repository import ProblemRegionRepository

    repo = ProblemRepository(db)
    problem = repo.create_from_pdf(
        source_pdf_id="PDF_TEST",
        page_number=1,
        problem_number=1,
        elective_subject="common",
        problem_image_path=str(tmp_path / "P_000001.png"),
        page_image_path=str(tmp_path / "page_001.png"),
        crop_box={"x": 0, "y": 0, "width": 200, "height": 100},
    )

    region_repo = ProblemRegionRepository(db)
    regions = await region_repo.list_by_problem(problem.id)

    assert len(regions) == 1
    assert regions[0].region_type == "full_problem"
    assert regions[0].label == "전체 문제"

    db.close()

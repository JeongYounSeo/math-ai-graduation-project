import importlib

import pytest


def _fresh_db_session(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")

    import app.core.database as database_module

    importlib.reload(database_module)
    database_module.create_tables()
    return database_module.SessionLocal()


@pytest.mark.asyncio
async def test_replace_choices_assigns_index_and_labels(tmp_path, monkeypatch):
    db = _fresh_db_session(tmp_path, monkeypatch)
    from app.repositories.problem_choice_repository import ProblemChoiceRepository

    repo = ProblemChoiceRepository(db)
    choices = await repo.replace_choices_for_problem(1, ["13/2", "27/4", "7", "29/4", "15/2"])

    assert [c.choice_index for c in choices] == [1, 2, 3, 4, 5]
    assert [c.choice_label for c in choices] == ["①", "②", "③", "④", "⑤"]
    assert choices[0].text == "13/2"
    assert all(c.is_correct is None for c in choices)

    db.close()


@pytest.mark.asyncio
async def test_replace_choices_removes_previous_choices(tmp_path, monkeypatch):
    db = _fresh_db_session(tmp_path, monkeypatch)
    from app.repositories.problem_choice_repository import ProblemChoiceRepository

    repo = ProblemChoiceRepository(db)
    await repo.replace_choices_for_problem(1, ["1", "2", "3"])
    new_choices = await repo.replace_choices_for_problem(1, ["a", "b"])

    all_choices = await repo.list_by_problem(1)
    assert len(all_choices) == 2
    assert [c.text for c in all_choices] == ["a", "b"]
    assert len(new_choices) == 2

    db.close()


@pytest.mark.asyncio
async def test_replace_choices_skips_empty_entries(tmp_path, monkeypatch):
    db = _fresh_db_session(tmp_path, monkeypatch)
    from app.repositories.problem_choice_repository import ProblemChoiceRepository

    repo = ProblemChoiceRepository(db)
    choices = await repo.replace_choices_for_problem(1, ["13/2", "  ", "", "7"])

    assert [c.text for c in choices] == ["13/2", "7"]
    assert [c.choice_index for c in choices] == [1, 2]

    db.close()


@pytest.mark.asyncio
async def test_get_update_delete_choice(tmp_path, monkeypatch):
    db = _fresh_db_session(tmp_path, monkeypatch)
    from app.repositories.problem_choice_repository import ProblemChoiceRepository
    from app.schemas.problem_choice_schema import ProblemChoiceUpdate

    repo = ProblemChoiceRepository(db)
    choices = await repo.replace_choices_for_problem(1, ["13/2"])
    choice_id = choices[0].id

    fetched = await repo.get(choice_id)
    assert fetched is not None

    updated = await repo.update(choice_id, ProblemChoiceUpdate(is_correct=True))
    assert updated.is_correct is True

    deleted = await repo.delete(choice_id)
    assert deleted is True
    assert await repo.get(choice_id) is None

    db.close()

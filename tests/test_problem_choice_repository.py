"""ProblemChoiceRepository 단위 테스트 (설계 §3, §6).

인메모리 SQLite 엔진에 전체 모델을 등록하고 격리된 세션으로 리포지토리를
직접 검증한다. Claude/네트워크 호출은 전혀 없다.

핵심 검증:
- replace_choices_for_problem: 기존 삭제 후 index 1..N, label ①..⑤,
  6개 이상이면 6번째 label None, text 보존, is_correct 전부 None(정답 추측 금지).
- create/get_by_problem_id/get_by_id/update/delete 동작.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db_base import Base

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

from app.repositories.problem_choice_repository import (
    ProblemChoiceRepository,
    CIRCLED_LABELS,
)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_create_and_get_by_id(db_session):
    repo = ProblemChoiceRepository(db_session)
    created = repo.create(
        {
            "problem_id": 1,
            "choice_index": 1,
            "choice_label": "\u2460",
            "text": "보기 1",
        }
    )
    assert created.id is not None
    fetched = repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched.problem_id == 1
    assert fetched.text == "보기 1"
    # 정답 추측 금지: 명시하지 않았으므로 None.
    assert fetched.is_correct is None
    assert fetched.is_distractor is None


def test_get_by_problem_id_sorted(db_session):
    repo = ProblemChoiceRepository(db_session)
    repo.create({"problem_id": 5, "choice_index": 3, "text": "c"})
    repo.create({"problem_id": 5, "choice_index": 1, "text": "a"})
    repo.create({"problem_id": 5, "choice_index": 2, "text": "b"})
    # 다른 problem 은 섞이지 않아야 함.
    repo.create({"problem_id": 6, "choice_index": 1, "text": "other"})

    choices = repo.get_by_problem_id(5)
    assert [c.choice_index for c in choices] == [1, 2, 3]
    assert [c.text for c in choices] == ["a", "b", "c"]


def test_get_by_problem_id_empty(db_session):
    repo = ProblemChoiceRepository(db_session)
    assert repo.get_by_problem_id(999) == []


def test_update_partial(db_session):
    repo = ProblemChoiceRepository(db_session)
    created = repo.create({"problem_id": 1, "choice_index": 1, "text": "old"})
    updated = repo.update(created.id, {"text": "new", "is_correct": True})
    assert updated is not None
    assert updated.text == "new"
    assert updated.is_correct is True
    # choice_index 는 건드리지 않았으므로 유지.
    assert updated.choice_index == 1


def test_update_missing_returns_none(db_session):
    repo = ProblemChoiceRepository(db_session)
    assert repo.update(12345, {"text": "x"}) is None


def test_delete(db_session):
    repo = ProblemChoiceRepository(db_session)
    created = repo.create({"problem_id": 1, "choice_index": 1, "text": "x"})
    assert repo.delete(created.id) is True
    assert repo.get_by_id(created.id) is None


def test_delete_missing_returns_false(db_session):
    repo = ProblemChoiceRepository(db_session)
    assert repo.delete(54321) is False


def test_replace_choices_basic(db_session):
    repo = ProblemChoiceRepository(db_session)
    inputs = ["1번 보기", "2번 보기", "3번 보기", "4번 보기", "5번 보기"]
    result = repo.replace_choices_for_problem(10, inputs)

    assert [c.choice_index for c in result] == [1, 2, 3, 4, 5]
    assert [c.choice_label for c in result] == CIRCLED_LABELS
    assert [c.text for c in result] == inputs
    # 정답 추측 금지: 전부 None.
    assert all(c.is_correct is None for c in result)
    assert all(c.is_distractor is None for c in result)
    # 정규화/latex 는 None.
    assert all(c.normalized_text is None for c in result)
    assert all(c.latex_text is None for c in result)


def test_replace_choices_more_than_five_labels_none(db_session):
    repo = ProblemChoiceRepository(db_session)
    inputs = [f"보기{i}" for i in range(1, 8)]  # 7개
    result = repo.replace_choices_for_problem(11, inputs)

    assert len(result) == 7
    assert [c.choice_index for c in result] == [1, 2, 3, 4, 5, 6, 7]
    # 처음 5개는 ①..⑤, 6번째 이후는 None.
    assert [c.choice_label for c in result[:5]] == CIRCLED_LABELS
    assert result[5].choice_label is None
    assert result[6].choice_label is None


def test_replace_choices_deletes_existing(db_session):
    repo = ProblemChoiceRepository(db_session)
    repo.replace_choices_for_problem(20, ["a", "b", "c"])
    # 다시 replace 하면 기존이 삭제되고 새로 생성.
    result = repo.replace_choices_for_problem(20, ["x", "y"])
    assert len(result) == 2
    assert [c.text for c in result] == ["x", "y"]
    # 전체 조회해도 2개뿐.
    assert len(repo.get_by_problem_id(20)) == 2


def test_replace_choices_is_correct_all_none(db_session):
    """정답 추측 금지: replace 후 모든 is_correct 가 None 이어야 한다."""
    repo = ProblemChoiceRepository(db_session)
    result = repo.replace_choices_for_problem(30, ["가", "나", "다", "라"])
    assert all(c.is_correct is None for c in result)

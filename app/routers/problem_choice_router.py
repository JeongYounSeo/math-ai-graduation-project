from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.repositories.problem_choice_repository import ProblemChoiceRepository
from app.schemas.problem_choice_schema import (
    ProblemChoiceSchema,
    ProblemChoiceCreate,
    ProblemChoiceUpdate,
    ProblemChoiceReplaceRequest,
    ProblemChoicesResponse,
)

# prefix 를 두지 않고 각 데코레이터에 full path 를 둔다.
# problems/{id}/choices 계열과 problem-choices/{id} 계열의 경로가 다르기 때문.
router = APIRouter(tags=["Problem Choices"])


@router.get("/api/problems/{problem_id}/choices", response_model=ProblemChoicesResponse)
def get_problem_choices(problem_id: int, db: Session = Depends(get_db)):
    repo = ProblemChoiceRepository(db)
    choices = repo.get_by_problem_id(problem_id)
    return ProblemChoicesResponse(problem_id=problem_id, choices=choices)


@router.post("/api/problems/{problem_id}/choices", response_model=ProblemChoiceSchema)
def create_problem_choice(
    problem_id: int,
    payload: ProblemChoiceCreate,
    db: Session = Depends(get_db),
):
    repo = ProblemChoiceRepository(db)
    data = payload.model_dump()
    data["problem_id"] = problem_id
    return repo.create(data)


@router.post(
    "/api/problems/{problem_id}/choices/replace",
    response_model=ProblemChoicesResponse,
)
def replace_problem_choices(
    problem_id: int,
    payload: ProblemChoiceReplaceRequest,
    db: Session = Depends(get_db),
):
    repo = ProblemChoiceRepository(db)
    choices = repo.replace_choices_for_problem(problem_id, payload.choices)
    return ProblemChoicesResponse(problem_id=problem_id, choices=choices)


@router.patch("/api/problem-choices/{choice_id}", response_model=ProblemChoiceSchema)
def update_problem_choice(
    choice_id: int,
    payload: ProblemChoiceUpdate,
    db: Session = Depends(get_db),
):
    repo = ProblemChoiceRepository(db)
    # exclude_unset 으로 실제 전달된 필드만 갱신한다.
    data = payload.model_dump(exclude_unset=True)
    updated = repo.update(choice_id, data)
    if updated is None:
        raise HTTPException(status_code=404, detail="보기를 찾을 수 없습니다.")
    return updated


@router.delete("/api/problem-choices/{choice_id}")
def delete_problem_choice(choice_id: int, db: Session = Depends(get_db)):
    repo = ProblemChoiceRepository(db)
    deleted = repo.delete(choice_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="보기를 찾을 수 없습니다.")
    return {"deleted": True}

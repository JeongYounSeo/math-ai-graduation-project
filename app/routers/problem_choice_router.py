from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from app.schemas.problem_choice_schema import (
    ProblemChoice,
    ProblemChoiceCreate,
    ProblemChoiceUpdate,
    ProblemChoiceReplaceRequest,
)
from app.repositories.problem_choice_repository import ProblemChoiceRepository

router = APIRouter(tags=["Problem Choices"])


@router.get("/api/problems/{problem_id}/choices", response_model=List[ProblemChoice])
async def get_problem_choices(problem_id: int, db: Session = Depends(get_db)):
    repo = ProblemChoiceRepository(db)
    return await repo.list_by_problem(problem_id)


@router.post("/api/problems/{problem_id}/choices", response_model=ProblemChoice)
async def create_problem_choice(problem_id: int, choice: ProblemChoiceCreate, db: Session = Depends(get_db)):
    if choice.problem_id != problem_id:
        raise HTTPException(status_code=400, detail="problem_id가 URL 경로와 일치하지 않습니다.")
    repo = ProblemChoiceRepository(db)
    return await repo.create(choice)


@router.post("/api/problems/{problem_id}/choices/replace", response_model=List[ProblemChoice])
async def replace_problem_choices(problem_id: int, request: ProblemChoiceReplaceRequest, db: Session = Depends(get_db)):
    repo = ProblemChoiceRepository(db)
    return await repo.replace_choices_for_problem(problem_id, request.choices)


@router.patch("/api/problem-choices/{choice_id}", response_model=ProblemChoice)
async def update_problem_choice(choice_id: int, choice_update: ProblemChoiceUpdate, db: Session = Depends(get_db)):
    repo = ProblemChoiceRepository(db)
    choice = await repo.update(choice_id, choice_update)
    if not choice:
        raise HTTPException(status_code=404, detail="Problem choice not found")
    return choice


@router.delete("/api/problem-choices/{choice_id}")
async def delete_problem_choice(choice_id: int, db: Session = Depends(get_db)):
    repo = ProblemChoiceRepository(db)
    deleted = await repo.delete(choice_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Problem choice not found")
    return {"message": "Problem choice deleted", "choice_id": choice_id}

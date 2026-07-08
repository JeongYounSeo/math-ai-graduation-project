from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.schemas.type_combination_schema import TypeCombination, TypeCombinationCreate
from app.repositories.type_combination_repository import TypeCombinationRepository

router = APIRouter()

@router.post("/", response_model=TypeCombination)
async def create_type_combination(
    combination: TypeCombinationCreate,
    db: Session = Depends(get_db)
):
    repo = TypeCombinationRepository(db)
    return await repo.create(combination)

@router.get("/", response_model=List[TypeCombination])
async def get_type_combinations(db: Session = Depends(get_db)):
    repo = TypeCombinationRepository(db)
    return await repo.get_all()

@router.get("/{combination_id}", response_model=TypeCombination)
async def get_type_combination(
    combination_id: str,
    db: Session = Depends(get_db)
):
    repo = TypeCombinationRepository(db)
    combination = await repo.get_by_combination_id(combination_id)
    if not combination:
        raise HTTPException(status_code=404, detail="Type combination not found")
    return combination
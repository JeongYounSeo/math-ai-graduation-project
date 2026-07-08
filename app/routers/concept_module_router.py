from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.schemas.concept_module_schema import ConceptModule, ConceptModuleCreate
from app.repositories.concept_module_repository import ConceptModuleRepository

router = APIRouter()

@router.post("/", response_model=ConceptModule)
async def create_concept_module(
    concept: ConceptModuleCreate,
    db: Session = Depends(get_db)
):
    repo = ConceptModuleRepository(db)
    return await repo.create(concept)

@router.get("/", response_model=List[ConceptModule])
async def get_concept_modules(db: Session = Depends(get_db)):
    repo = ConceptModuleRepository(db)
    return await repo.get_all()

@router.get("/{concept_id}", response_model=ConceptModule)
async def get_concept_module(
    concept_id: str,
    db: Session = Depends(get_db)
):
    repo = ConceptModuleRepository(db)
    concept = await repo.get_by_concept_id(concept_id)
    if not concept:
        raise HTTPException(status_code=404, detail="Concept module not found")
    return concept
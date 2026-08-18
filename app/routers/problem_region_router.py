from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from app.schemas.problem_region_schema import ProblemRegion, ProblemRegionCreate, ProblemRegionUpdate
from app.repositories.problem_region_repository import ProblemRegionRepository

router = APIRouter(tags=["Problem Regions"])


@router.get("/api/problems/{problem_id}/regions", response_model=List[ProblemRegion])
async def get_problem_regions(problem_id: int, db: Session = Depends(get_db)):
    repo = ProblemRegionRepository(db)
    return await repo.list_by_problem(problem_id)


@router.post("/api/problems/{problem_id}/regions", response_model=ProblemRegion)
async def create_problem_region(problem_id: int, region: ProblemRegionCreate, db: Session = Depends(get_db)):
    if region.problem_id != problem_id:
        raise HTTPException(status_code=400, detail="problem_id가 URL 경로와 일치하지 않습니다.")
    repo = ProblemRegionRepository(db)
    return await repo.create(region)


@router.patch("/api/problem-regions/{region_id}", response_model=ProblemRegion)
async def update_problem_region(region_id: int, region_update: ProblemRegionUpdate, db: Session = Depends(get_db)):
    repo = ProblemRegionRepository(db)
    region = await repo.update(region_id, region_update)
    if not region:
        raise HTTPException(status_code=404, detail="Problem region not found")
    return region


@router.delete("/api/problem-regions/{region_id}")
async def delete_problem_region(region_id: int, db: Session = Depends(get_db)):
    repo = ProblemRegionRepository(db)
    deleted = await repo.delete(region_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Problem region not found")
    return {"message": "Problem region deleted", "region_id": region_id}

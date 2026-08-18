from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from app.models.problem_region import ProblemRegion as ProblemRegionModel
from app.schemas.problem_region_schema import ProblemRegion, ProblemRegionCreate, ProblemRegionUpdate
from app.repositories.problem_region_repository import ProblemRegionRepository
from app.repositories.problem_repository import ProblemRepository
from app.services.problem_region_crop_service import ProblemRegionCropService, resolve_source_image_path

router = APIRouter(tags=["Problem Regions"])


async def _autocrop_if_ready(region: ProblemRegionModel, db: Session) -> ProblemRegionModel:
    """coordinate가 모두 채워진 region이면 저장 직후 자동으로 crop을 시도한다.

    좌표가 없거나, source 이미지를 아직 찾을 수 없거나 crop이 실패하면
    조용히 건너뛴다 (자동 트리거는 best-effort이고, 명시적 재생성 엔드포인트가
    따로 있으므로 CRUD 응답 자체를 실패시키지 않는다).
    """
    if any(coord is None for coord in (region.x1, region.y1, region.x2, region.y2)):
        return region

    problem_repo = ProblemRepository(db)
    problem = await problem_repo.get_by_id(region.problem_id)
    if not problem:
        return region

    source_image_path = resolve_source_image_path(region, problem)
    if not source_image_path:
        return region

    try:
        cropped_path = ProblemRegionCropService().crop_and_save(region, source_image_path)
    except (ValueError, FileNotFoundError):
        return region

    region_repo = ProblemRegionRepository(db)
    updated = await region_repo.update(region.id, ProblemRegionUpdate(cropped_image_path=cropped_path))
    return updated or region


@router.get("/api/problems/{problem_id}/regions", response_model=List[ProblemRegion])
async def get_problem_regions(problem_id: int, db: Session = Depends(get_db)):
    repo = ProblemRegionRepository(db)
    return await repo.list_by_problem(problem_id)


@router.post("/api/problems/{problem_id}/regions", response_model=ProblemRegion)
async def create_problem_region(problem_id: int, region: ProblemRegionCreate, db: Session = Depends(get_db)):
    if region.problem_id != problem_id:
        raise HTTPException(status_code=400, detail="problem_id가 URL 경로와 일치하지 않습니다.")
    repo = ProblemRegionRepository(db)
    db_region = await repo.create(region)
    if region.cropped_image_path is None:
        db_region = await _autocrop_if_ready(db_region, db)
    return db_region


@router.patch("/api/problem-regions/{region_id}", response_model=ProblemRegion)
async def update_problem_region(region_id: int, region_update: ProblemRegionUpdate, db: Session = Depends(get_db)):
    repo = ProblemRegionRepository(db)
    region = await repo.update(region_id, region_update)
    if not region:
        raise HTTPException(status_code=404, detail="Problem region not found")
    if "cropped_image_path" not in region_update.model_dump(exclude_unset=True):
        region = await _autocrop_if_ready(region, db)
    return region


@router.post("/api/problem-regions/{region_id}/crop", response_model=ProblemRegion)
async def crop_problem_region(region_id: int, db: Session = Depends(get_db)):
    repo = ProblemRegionRepository(db)
    region = await repo.get(region_id)
    if not region:
        raise HTTPException(status_code=404, detail="Problem region not found")

    problem_repo = ProblemRepository(db)
    problem = await problem_repo.get_by_id(region.problem_id)
    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found")

    source_image_path = resolve_source_image_path(region, problem)
    try:
        cropped_path = ProblemRegionCropService().crop_and_save(region, source_image_path)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    updated = await repo.update(region_id, ProblemRegionUpdate(cropped_image_path=cropped_path))
    return updated


@router.delete("/api/problem-regions/{region_id}")
async def delete_problem_region(region_id: int, db: Session = Depends(get_db)):
    repo = ProblemRegionRepository(db)
    deleted = await repo.delete(region_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Problem region not found")
    return {"message": "Problem region deleted", "region_id": region_id}

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.schemas.problem_schema import Problem, ProblemCreate, ProblemUpdate
from app.schemas.analysis_schema import AnalysisResponse
from app.schemas.problem_region_schema import (
    ProblemRegionsResponse,
    ProblemRegionSchema,
    ProblemRegionItemSchema,
)
from app.repositories.problem_repository import ProblemRepository
from app.repositories.problem_region_repository import ProblemRegionRepository
from app.repositories.problem_region_item_repository import ProblemRegionItemRepository
from app.services.problem_analysis_service import ProblemAnalysisService
from app.services.prompt_builder_service import PromptBuilderService
from app.services.problem_region_extraction_service import ProblemRegionExtractionService
from app.services.problem_ocr_apply_service import ProblemOcrApplyService

router = APIRouter()


@router.post("/", response_model=Problem)
async def create_problem(problem: ProblemCreate, db: Session = Depends(get_db)):
    repo = ProblemRepository(db)
    return await repo.create(problem)


@router.get("/", response_model=List[Problem])
async def get_problems(
    status: Optional[str] = Query(default="unclassified"),
    source_pdf_id: Optional[str] = None,
    elective_subject: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    repo = ProblemRepository(db)
    return await repo.get_filtered(
        status=status,
        source_pdf_id=source_pdf_id,
        elective_subject=elective_subject,
        page=page,
        page_size=page_size,
    )


@router.get("/{problem_id}", response_model=Problem)
async def get_problem(problem_id: int, db: Session = Depends(get_db)):
    repo = ProblemRepository(db)
    problem = await repo.get_by_id(problem_id)
    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found")
    return problem


@router.get("/{problem_id}/regions", response_model=ProblemRegionsResponse)
async def get_problem_regions(problem_id: int, db: Session = Depends(get_db)):
    repo = ProblemRepository(db)
    problem = await repo.get_by_id(problem_id)
    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found")

    region_repo = ProblemRegionRepository(db)
    item_repo = ProblemRegionItemRepository(db)

    regions = region_repo.get_by_problem_id(problem_id)
    region_schemas = []
    for region in regions:
        items = item_repo.get_by_region_id(region.id)
        region_schema = ProblemRegionSchema.model_validate(region)
        region_schema.items = [
            ProblemRegionItemSchema.model_validate(item) for item in items
        ]
        region_schemas.append(region_schema)

    return ProblemRegionsResponse(problem_id=problem_id, regions=region_schemas)


@router.patch("/{problem_id}", response_model=Problem)
async def patch_problem(problem_id: int, problem_update: ProblemUpdate, db: Session = Depends(get_db)):
    repo = ProblemRepository(db)
    problem = await repo.update(problem_id, problem_update)
    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found")
    return problem


@router.delete("/{problem_id}")
async def delete_problem(problem_id: int, db: Session = Depends(get_db)):
    repo = ProblemRepository(db)
    deleted = await repo.delete(problem_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Problem not found")
    return {"message": "Problem marked as excluded", "problem_id": problem_id}


@router.post("/{problem_id}/analyze", response_model=AnalysisResponse)
async def analyze_problem(problem_id: int, db: Session = Depends(get_db)):
    repo = ProblemRepository(db)
    problem = await repo.get_by_id(problem_id)
    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found")

    prompt_builder = PromptBuilderService()
    analysis_service = ProblemAnalysisService(prompt_builder)
    analysis_result = await analysis_service.analyze_problem(problem.raw_text or "")

    update_data = ProblemUpdate(
        extracted_conditions=analysis_result["extracted_conditions"],
        large_unit=analysis_result["large_unit"],
        middle_unit=analysis_result["middle_unit"],
        detected_module_ids=analysis_result["detected_module_ids"],
    )
    await repo.update(problem_id, update_data)

    return AnalysisResponse(**analysis_result)



@router.post("/{problem_id}/extract-regions", response_model=ProblemRegionsResponse)
async def extract_problem_regions(problem_id: int, db: Session = Depends(get_db)):
    """Run Claude Vision region extraction for a single problem on demand.

    Triggered by the admin UI button. Re-runs extraction (replacing any
    existing regions) and returns the freshly detected regions.
    """
    repo = ProblemRepository(db)
    problem = await repo.get_by_id(problem_id)
    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found")

    # Clear any previously extracted regions so a re-run does not accumulate duplicates.
    ProblemRegionRepository(db).delete_by_problem_id(problem_id)

    service = ProblemRegionExtractionService(db)
    result = service.extract_regions(problem)
    if not result.success:
        detail = f"region extraction failed (type={result.failure_type})"
        if result.errors:
            detail += ": " + "; ".join(result.errors)
        raise HTTPException(status_code=502, detail=detail)

    region_repo = ProblemRegionRepository(db)
    item_repo = ProblemRegionItemRepository(db)
    regions = region_repo.get_by_problem_id(problem_id)
    region_schemas = []
    for region in regions:
        items = item_repo.get_by_region_id(region.id)
        region_schema = ProblemRegionSchema.model_validate(region)
        region_schema.items = [
            ProblemRegionItemSchema.model_validate(item) for item in items
        ]
        region_schemas.append(region_schema)
    return ProblemRegionsResponse(problem_id=problem_id, regions=region_schemas)



@router.post("/{problem_id}/apply-ocr")
async def apply_ocr(problem_id: int, result: dict, db: Session = Depends(get_db)):
    """외부 OCR 결과(result dict)를 문제에 반영한다(설계 §5, 연결안 B).

    body 예:
        {"answer_type": "multiple_choice", "choices": ["1","2","3","4","5"],
         "crop_box": {"x":..,"y":..,"width":..,"height":..}}

    - 객관식이면 ProblemChoice 재생성 + Problem.choices 동기화.
    - full_problem region 이 없으면 crop_box 로 자동 생성.
    반환: {"choices_replaced": int, "full_problem_region_created": bool}
    """
    repo = ProblemRepository(db)
    problem = await repo.get_by_id(problem_id)
    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found")
    summary = ProblemOcrApplyService(db).apply_ocr_result(problem_id, result)
    return summary

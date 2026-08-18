from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.schemas.problem_schema import Problem, ProblemCreate, ProblemUpdate, OCRRunResponse
from app.schemas.analysis_schema import AnalysisResponse
from app.schemas.problem_region_schema import ProblemRegionUpdate
from app.repositories.problem_repository import ProblemRepository
from app.repositories.problem_choice_repository import ProblemChoiceRepository
from app.repositories.problem_region_repository import ProblemRegionRepository
from app.services.problem_analysis_service import ProblemAnalysisService
from app.services.prompt_builder_service import PromptBuilderService
from app.services.problem_ocr_service import ProblemOCRService, get_ocr_provider
from app.services.ocr_providers.base import OCRProvider

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


@router.post("/{problem_id}/ocr", response_model=OCRRunResponse)
async def run_problem_ocr(
    problem_id: int,
    db: Session = Depends(get_db),
    provider: OCRProvider = Depends(get_ocr_provider),
):
    repo = ProblemRepository(db)
    problem = await repo.get_by_id(problem_id)
    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found")
    if not problem.problem_image_path:
        raise HTTPException(status_code=400, detail="OCR을 실행할 이미지가 없습니다")

    ocr_service = ProblemOCRService(provider)
    try:
        result = await ocr_service.run_ocr_for_problem(problem)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    await repo.update(
        problem_id,
        ProblemUpdate(raw_ocr_text=result.body_text, latex_text=result.latex_text),
    )

    if result.choices:
        choice_repo = ProblemChoiceRepository(db)
        await choice_repo.replace_choices_for_problem(problem_id, result.choices)

    region_repo = ProblemRegionRepository(db)
    regions = await region_repo.list_by_problem_and_type(problem_id, "full_problem")
    region = regions[0] if regions else None
    if region is None:
        refreshed_problem = await repo.get_by_id(problem_id)
        region = region_repo.create_full_problem_region_from_problem(refreshed_problem)
    if region is not None:
        await region_repo.update(
            region.id,
            ProblemRegionUpdate(
                extracted_text=result.body_text,
                latex_text=result.latex_text,
                confidence=result.confidence,
                provider=result.provider_name,
            ),
        )

    return OCRRunResponse(
        problem_id=problem_id,
        body_text=result.body_text,
        choices=result.choices,
        confidence=result.confidence,
        provider=result.provider_name,
    )
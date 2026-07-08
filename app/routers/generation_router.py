from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.schemas.generation_schema import GenerationRequest, GenerationResponse
from app.services.generation_service import GenerationService
from app.services.prompt_builder_service import PromptBuilderService
from app.repositories.solution_module_repository import SolutionModuleRepository
from app.repositories.type_combination_repository import TypeCombinationRepository
from app.repositories.generated_problem_repository import GeneratedProblemRepository
from app.utils.id_generator import generate_id

router = APIRouter()

@router.post("/problem", response_model=GenerationResponse)
async def generate_problem(
    request: GenerationRequest,
    db: Session = Depends(get_db)
):
    prompt_builder = PromptBuilderService()
    solution_repo = SolutionModuleRepository(db)
    combination_repo = TypeCombinationRepository(db)
    generated_repo = GeneratedProblemRepository(db)
    
    service = GenerationService(prompt_builder, solution_repo, combination_repo)
    result = await service.generate_problem(
        request.selected_module_ids,
        request.selected_combination_id,
        request.difficulty_level,
        request.generation_goal
    )
    
    # 생성된 문제 저장
    generated_problem_id = generate_id()
    generated_problem_data = {
        "generated_problem_id": generated_problem_id,
        "used_module_ids": request.selected_module_ids,
        "used_combination_id": request.selected_combination_id,
        "problem_text": result["mock_problem"]["problem_text"],
        "problem_latex": result["mock_problem"]["problem_latex"],
        "answer": result["mock_problem"]["answer"],
        "solution_text": result["mock_problem"]["solution_text"]
    }
    
    await generated_repo.create(generated_problem_data)
    
    return GenerationResponse(
        generated_problem_id=generated_problem_id,
        prompt_used=result["prompt_used"],
        mock_problem=result["mock_problem"]
    )
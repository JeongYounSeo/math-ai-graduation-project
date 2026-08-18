from fastapi import APIRouter
from app.schemas.analysis_schema import AnalysisRequest, AnalysisResponse
from app.services.problem_analysis_service import ProblemAnalysisService
from app.services.prompt_builder_service import PromptBuilderService

router = APIRouter()

@router.post("/", response_model=AnalysisResponse)
async def analyze_problem_text(request: AnalysisRequest):
    prompt_builder = PromptBuilderService()
    service = ProblemAnalysisService(prompt_builder)
    return await service.analyze_problem(request.problem_text)
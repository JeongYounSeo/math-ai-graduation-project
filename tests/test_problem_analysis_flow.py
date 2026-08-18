import pytest
from app.services.problem_analysis_service import ProblemAnalysisService
from app.services.prompt_builder_service import PromptBuilderService

@pytest.mark.asyncio
async def test_problem_analysis_service():
    """문제 분석 서비스 테스트"""
    prompt_builder = PromptBuilderService()
    service = ProblemAnalysisService(prompt_builder)
    
    problem_text = "삼각형 ABC에서 AB = 5, BC = 6, ∠ABC = 60° 일 때, AC의 길이를 구하시오."
    
    result = await service.analyze_problem(problem_text)
    
    assert "prompt_used" in result
    assert "mock_analysis" in result
    assert result["mock_analysis"]["large_unit"] == "기하"
    assert "TRI_COSINE_RULE_RELATION" in result["mock_analysis"]["detected_solution_modules"]
from typing import Dict, Any, List
from app.services.prompt_builder_service import PromptBuilderService

class ProblemAnalysisService:
    def __init__(self, prompt_builder: PromptBuilderService):
        self.prompt_builder = prompt_builder

    async def analyze_problem(self, problem_text: str) -> Dict[str, Any]:
        # 프롬프트 생성
        prompt = self.prompt_builder.build_problem_analysis_prompt(problem_text)
        
        # 실제 AI 호출 대신 모의 분석 결과 반환
        mock_analysis = {
            "large_unit": "기하",
            "middle_unit": "삼각형과 삼각함수",
            "core_concepts": ["코사인 법칙", "삼각형"],
            "detected_solution_modules": ["TRI_COSINE_RULE_RELATION"],
            "conditions": ["AB = 5", "BC = 6", "∠ABC = 60°"],
            "target_value": "AC의 길이",
            "required_relations": ["코사인 법칙"],
            "solution_flow_summary": ["코사인 법칙 적용", "계산"]
        }
        
        return {
            "prompt_used": prompt,
            "mock_analysis": mock_analysis,
            "extracted_conditions": mock_analysis["conditions"],
            "large_unit": mock_analysis["large_unit"],
            "middle_unit": mock_analysis["middle_unit"],
            "detected_module_ids": mock_analysis["detected_solution_modules"]
        }
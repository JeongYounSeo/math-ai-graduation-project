from typing import Dict, Any
from app.services.prompt_builder_service import PromptBuilderService

class VerificationService:
    def __init__(self, prompt_builder: PromptBuilderService):
        self.prompt_builder = prompt_builder

    async def verify_problem(
        self,
        problem_text: str,
        solution_text: str,
        expected_modules: List[str]
    ) -> Dict[str, Any]:
        # 프롬프트 생성
        prompt = self.prompt_builder.build_verification_prompt(problem_text, solution_text, expected_modules)
        
        # 실제 검증 대신 모의 결과 반환
        mock_verification = {
            "is_solvable": True,
            "has_contradiction": False,
            "uses_expected_modules": True,
            "difficulty_assessment": "medium",
            "verification_notes": "문제가 올바르게 구성되어 있으며, 코사인 법칙을 사용합니다."
        }
        
        return {
            "prompt_used": prompt,
            "mock_verification": mock_verification
        }
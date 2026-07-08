from typing import Dict, Any, List
from app.services.prompt_builder_service import PromptBuilderService

class SolutionModuleService:
    def __init__(self, prompt_builder: PromptBuilderService):
        self.prompt_builder = prompt_builder

    async def create_module_from_description(self, user_description: str) -> Dict[str, Any]:
        # 프롬프트 생성
        prompt = self.prompt_builder.build_solution_module_extraction_prompt(user_description)
        
        # 실제 AI 호출 대신 모의 SolutionModule 반환
        mock_module = {
            "module_id": "TRI_COSINE_RULE_RELATION",
            "name": "코사인 법칙 미지수 관계식 활용형",
            "large_unit": "기하",
            "middle_unit": "삼각형과 삼각함수",
            "description": "코사인 법칙을 이용해 변과 각 사이의 관계식을 세우고, 부족한 미지수는 추가 조건에서 관계식으로 연결하여 해결하는 유형",
            "trigger_conditions": ["삼각형에서 변과 각 사이의 관계가 필요하다"],
            "core_concepts": ["코사인 법칙"],
            "core_relations": [{"name": "코사인 법칙", "formula_latex": r"c^2 = a^2 + b^2 - 2ab\cos C"}],
            "input_variables": ["a", "b", "c", "C"],
            "output_targets": ["c"],
            "known_unknown_patterns": [{"known": ["a", "b", "C"], "unknown": ["c"]}],
            "solution_steps": ["코사인 법칙 적용"],
            "can_combine_with": ["TRIANGLE_AREA_FORMULA"],
            "generation_rules": {"must_keep": ["코사인 법칙"], "can_change": ["변 길이"]}
        }
        
        return {
            "prompt_used": prompt,
            "mock_module": mock_module
        }
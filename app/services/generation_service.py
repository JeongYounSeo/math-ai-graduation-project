from typing import Dict, Any, List
from app.services.prompt_builder_service import PromptBuilderService
from app.repositories.solution_module_repository import SolutionModuleRepository
from app.repositories.type_combination_repository import TypeCombinationRepository

class GenerationService:
    def __init__(
        self,
        prompt_builder: PromptBuilderService,
        solution_module_repo: SolutionModuleRepository,
        type_combination_repo: TypeCombinationRepository
    ):
        self.prompt_builder = prompt_builder
        self.solution_module_repo = solution_module_repo
        self.type_combination_repo = type_combination_repo

    async def generate_problem(
        self,
        selected_module_ids: List[str],
        selected_combination_id: str = None,
        difficulty_level: str = "medium",
        generation_goal: str = ""
    ) -> Dict[str, Any]:
        # 선택된 모듈과 조합 조회
        modules = []
        for module_id in selected_module_ids:
            module = await self.solution_module_repo.get_by_module_id(module_id)
            if module:
                modules.append(module)
        
        combination = None
        if selected_combination_id:
            combination = await self.type_combination_repo.get_by_combination_id(selected_combination_id)
        
        # 프롬프트 생성
        prompt = self.prompt_builder.build_problem_generation_prompt(modules, combination, generation_goal)
        
        # 실제 AI 호출 대신 모의 문제 생성
        mock_problem = {
            "problem_text": "삼각형 ABC에서 AB = 7, BC = 8, ∠ABC = 45° 일 때, AC의 길이를 구하시오.",
            "problem_latex": r"\triangle ABC에서 $AB = 7$, $BC = 8$, $\angle ABC = 45^\circ$ 일 때, $AC$의 길이를 구하시오.",
            "answer": r"\sqrt{7^2 + 8^2 - 2 \cdot 7 \cdot 8 \cdot \cos 45^\circ}",
            "solution_text": "코사인 법칙에 따라 AC² = AB² + BC² - 2·AB·BC·cos∠ABC = 49 + 64 - 2·7·8·(√2/2) ≈ 113 - 56√2"
        }
        
        return {
            "prompt_used": prompt,
            "mock_problem": mock_problem
        }
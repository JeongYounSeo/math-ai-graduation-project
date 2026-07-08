from typing import Dict, Any, List
from app.models.solution_module import SolutionModule
from app.models.type_combination import TypeCombination

class PromptBuilderService:
    def build_problem_analysis_prompt(self, problem_text: str) -> str:
        return f"""
다음 수학 문제를 분석하여 JSON 형식으로 정보를 추출하시오.

문제: {problem_text}

출력 형식:
{{
  "large_unit": "큰 단원 (예: 수학 I, 기하)",
  "middle_unit": "중간 단원 (예: 삼각형과 삼각함수)",
  "core_concepts": ["핵심 개념 리스트"],
  "detected_solution_modules": ["적용 가능한 소유형 모듈 ID 리스트"],
  "conditions": ["주어진 조건 리스트"],
  "target_value": "구해야 할 값",
  "required_relations": ["필요한 관계식 리스트"],
  "solution_flow_summary": ["풀이 흐름 요약"]
}}
"""

    def build_solution_module_extraction_prompt(self, user_description: str) -> str:
        return f"""
사용자가 설명한 풀이 유형을 SolutionModule JSON 형식으로 변환하시오.

설명: {user_description}

출력 형식: SolutionModule JSON 구조
"""

    def build_problem_generation_prompt(
        self,
        modules: List[SolutionModule],
        combination: TypeCombination = None,
        generation_goal: str = ""
    ) -> str:
        modules_info = "\n".join([f"- {m.module_id}: {m.name}" for m in modules])
        combination_info = f"조합: {combination.name if combination else '없음'}"
        
        return f"""
다음 소유형 모듈들을 기반으로 새로운 수학 문제를 생성하시오.

사용할 모듈들:
{modules_info}

{combination_info}

생성 목표: {generation_goal}

출력 형식: 새로운 문제의 텍스트, LaTeX, 답, 풀이
"""

    def build_verification_prompt(
        self,
        problem_text: str,
        solution_text: str,
        expected_modules: List[str]
    ) -> str:
        return f"""
다음 문제를 검증하시오.

문제: {problem_text}
풀이: {solution_text}
예상 모듈: {expected_modules}

검증 항목:
- 풀이 가능성
- 조건 모순 여부
- 예상 모듈 사용 여부
"""
def build_solution_module_extraction_prompt(user_description: str) -> str:
    return f"""
사용자가 설명한 풀이 유형을 SolutionModule JSON 형식으로 변환하시오.

설명: {user_description}

출력 형식: SolutionModule JSON 구조 (모든 필드 포함)
"""
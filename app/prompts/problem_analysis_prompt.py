def build_problem_analysis_prompt(problem_text: str) -> str:
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
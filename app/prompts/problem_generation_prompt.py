def build_problem_generation_prompt(modules, combination, generation_goal) -> str:
    modules_info = "\n".join([f"- {m['module_id']}: {m['name']}" for m in modules]) if modules else "없음"
    combination_info = f"조합: {combination['name']}" if combination else "없음"
    
    return f"""
다음 소유형 모듈들을 기반으로 새로운 수학 문제를 생성하시오.

사용할 모듈들:
{modules_info}

{combination_info}

생성 목표: {generation_goal}

출력 형식: 새로운 문제의 텍스트, LaTeX, 답, 풀이
"""
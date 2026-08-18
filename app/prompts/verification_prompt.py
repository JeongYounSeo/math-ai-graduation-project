def build_verification_prompt(problem_text: str, solution_text: str, expected_modules) -> str:
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
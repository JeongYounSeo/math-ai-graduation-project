import re
from typing import Optional

def extract_math_expressions(text: str) -> list:
    """텍스트에서 수학 표현식 추출"""
    # 간단한 패턴으로 $...$ 또는 $$...$$ 추출
    patterns = [r'\$(.*?)\$', r'\$\$(.*?)\$\$']
    expressions = []
    for pattern in patterns:
        matches = re.findall(pattern, text)
        expressions.extend(matches)
    return expressions

def validate_latex(latex_str: str) -> bool:
    """LaTeX 문법 검증 (간단한 검증)"""
    # 기본적인 괄호 매칭 검증
    stack = []
    brackets = {'{': '}', '[': ']', '(': ')'}
    
    for char in latex_str:
        if char in brackets:
            stack.append(char)
        elif char in brackets.values():
            if not stack:
                return False
            if brackets[stack.pop()] != char:
                return False
    
    return len(stack) == 0
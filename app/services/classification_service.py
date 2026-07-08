from typing import Dict, Any, List

class ClassificationService:
    async def classify_problem(self, extracted_text: str, latex_text: str) -> Dict[str, Any]:
        # 실제 분류 로직 대신 스텁
        return {
            "large_unit": "기하",
            "middle_unit": "삼각형과 삼각함수",
            "difficulty_level": "중",
            "detected_module_ids": ["TRI_COSINE_RULE_RELATION"]
        }
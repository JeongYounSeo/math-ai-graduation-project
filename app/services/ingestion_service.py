from typing import Dict, Any, Optional
from abc import ABC, abstractmethod

class IngestionServiceInterface(ABC):
    @abstractmethod
    async def ingest_problem(self, source_type: str, source_data: bytes) -> Dict[str, Any]:
        """문제 소스를 받아 텍스트로 변환"""
        pass

class IngestionService(IngestionServiceInterface):
    async def ingest_problem(self, source_type: str, source_data: bytes) -> Dict[str, Any]:
        # 실제 OCR/이미지 처리 대신 스텁
        if source_type == "image":
            return {
                "raw_text": "삼각형 ABC에서 AB = 5, BC = 6, ∠ABC = 60° 일 때, AC의 길이를 구하시오.",
                "latex_text": r"\triangle ABC에서 $AB = 5$, $BC = 6$, $\angle ABC = 60^\circ$ 일 때, $AC$의 길이를 구하시오."
            }
        elif source_type == "pdf":
            return {
                "raw_text": "PDF에서 추출된 텍스트",
                "latex_text": r"PDF에서 추출된 LaTeX"
            }
        else:
            return {
                "raw_text": "텍스트 입력",
                "latex_text": r"텍스트 입력 LaTeX"
            }
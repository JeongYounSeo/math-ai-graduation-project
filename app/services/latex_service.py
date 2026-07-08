from typing import Dict, Any, Optional
from abc import ABC, abstractmethod

class LaTeXServiceInterface(ABC):
    @abstractmethod
    async def extract_latex_from_image(self, image_data: bytes) -> str:
        """이미지에서 LaTeX 수식 추출"""
        pass

class LaTeXService(LaTeXServiceInterface):
    async def extract_latex_from_image(self, image_data: bytes) -> str:
        # 실제 LaTeX 인식 대신 스텁
        return r"\triangle ABC에서 $AB = 5$, $BC = 6$, $\angle ABC = 60^\circ$ 일 때, $AC$의 길이를 구하시오."
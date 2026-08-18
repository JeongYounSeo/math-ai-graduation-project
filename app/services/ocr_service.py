from typing import Dict, Any, Optional
from abc import ABC, abstractmethod

class OCRServiceInterface(ABC):
    @abstractmethod
    async def extract_text_from_image(self, image_data: bytes) -> str:
        """이미지에서 텍스트 추출"""
        pass

class OCRService(OCRServiceInterface):
    async def extract_text_from_image(self, image_data: bytes) -> str:
        # 실제 OCR 대신 스텁
        return "삼각형 ABC에서 AB = 5, BC = 6, ∠ABC = 60° 일 때, AC의 길이를 구하시오."
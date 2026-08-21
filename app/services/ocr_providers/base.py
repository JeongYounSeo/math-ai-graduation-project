from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class OCRResult:
    """OCR/비전 API 호출 결과. 정답 정보는 담지 않는다 (정답은 추측하지 않는다)."""

    body_text: Optional[str]
    choices: List[str] = field(default_factory=list)
    latex_text: Optional[str] = None
    confidence: Optional[float] = None
    provider_name: str = "unknown"


class OCRProvider(ABC):
    """문제 이미지에서 본문/보기 텍스트를 추출하는 provider 인터페이스.

    벤더(Claude vision, Gemini, Mathpix 등)에 종속되지 않도록 이 인터페이스로 분리한다.
    """

    @abstractmethod
    async def extract(self, image_path: str) -> OCRResult:
        ...

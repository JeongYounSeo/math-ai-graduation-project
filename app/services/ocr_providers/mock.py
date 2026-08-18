from pathlib import Path
from typing import List, Optional

from app.services.ocr_providers.base import OCRProvider, OCRResult


class MockOCRProvider(OCRProvider):
    """테스트/로컬 개발용 mock provider. 실제 네트워크 호출 없이 동작한다.

    app.services.problem_analysis_service.ProblemAnalysisService 등 이 프로젝트의
    다른 mock 서비스와 동일하게, 파일 존재 여부만 확인하고 고정된 더미 결과를 반환한다.
    생성자로 원하는 결과를 override할 수 있어 테스트에서 다양한 시나리오(보기 있음/없음)를
    쉽게 구성할 수 있다.
    """

    def __init__(
        self,
        body_text: Optional[str] = "[MOCK OCR] 삼각형 ABC에서 AB = 5, BC = 6, ∠ABC = 60° 일 때, AC의 길이를 구하시오.",
        choices: Optional[List[str]] = None,
        latex_text: Optional[str] = None,
        confidence: Optional[float] = 0.5,
    ):
        self._body_text = body_text
        self._choices = list(choices) if choices is not None else []
        self._latex_text = latex_text
        self._confidence = confidence

    async def extract(self, image_path: str) -> OCRResult:
        if not image_path or not Path(image_path).exists():
            raise FileNotFoundError(f"OCR 대상 이미지가 존재하지 않습니다: {image_path}")

        return OCRResult(
            body_text=self._body_text,
            choices=list(self._choices),
            latex_text=self._latex_text,
            confidence=self._confidence,
            provider_name="mock",
        )

from app.models.problem import Problem
from app.services.ocr_providers.base import OCRProvider, OCRResult


class ProblemOCRService:
    def __init__(self, provider: OCRProvider):
        self.provider = provider

    async def run_ocr_for_problem(self, problem: Problem) -> OCRResult:
        """problem.problem_image_path (없으면 page_image_path)를 provider에 전달해 OCR을 실행한다."""
        image_path = problem.problem_image_path or problem.page_image_path
        if not image_path:
            raise ValueError("OCR을 실행할 이미지가 없습니다")
        return await self.provider.extract(image_path)


def get_ocr_provider() -> OCRProvider:
    """FastAPI 의존성 기본 구현. 테스트에서는 app.dependency_overrides로 MockOCRProvider로 교체한다."""
    from app.services.ocr_providers.claude_vision import ClaudeVisionOCRProvider

    return ClaudeVisionOCRProvider()

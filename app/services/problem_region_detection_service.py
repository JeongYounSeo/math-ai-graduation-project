from typing import List

from sqlalchemy.orm import Session

from app.models.problem import Problem
from app.models.problem_region import ProblemRegion
from app.repositories.problem_region_repository import ProblemRegionRepository
from app.repositories.problem_repository import ProblemRepository
from app.schemas.problem_region_schema import ProblemRegionCreate, ProblemRegionUpdate
from app.services.problem_region_crop_service import ProblemRegionCropService, resolve_source_image_path
from app.services.region_detectors.base import DetectedRegion, RegionDetector


class ProblemRegionDetectionService:
    def __init__(self, db: Session, detector: RegionDetector):
        self.db = db
        self.detector = detector
        self.problem_repo = ProblemRepository(db)
        self.region_repo = ProblemRegionRepository(db)
        self.crop_service = ProblemRegionCropService()

    async def detect_and_save_regions(self, problem_id: int) -> List[ProblemRegion]:
        """full_problem region 조회 -> detector 호출 -> 결과마다 ProblemRegion 생성 및 crop."""
        problem = await self.problem_repo.get_by_id(problem_id)
        if not problem:
            raise ValueError(f"Problem not found: {problem_id}")

        image_path = problem.problem_image_path or problem.page_image_path
        if not image_path:
            raise ValueError("탐지를 실행할 이미지가 없습니다")

        full_problem_regions = await self.region_repo.list_by_problem_and_type(problem_id, "full_problem")
        full_problem_region = full_problem_regions[0] if full_problem_regions else None
        if full_problem_region is None:
            full_problem_region = self.region_repo.create_full_problem_region_from_problem(problem)
        parent_region_id = full_problem_region.id if full_problem_region else None

        detected = await self.detector.detect(problem)
        provider_name = getattr(self.detector, "provider_name", type(self.detector).__name__)

        created_regions: List[ProblemRegion] = []
        for index, item in enumerate(detected):
            region = await self.region_repo.create(
                ProblemRegionCreate(
                    problem_id=problem_id,
                    parent_region_id=parent_region_id,
                    region_type=item.region_type,
                    label=item.reason,
                    order_index=index,
                    x1=item.x1,
                    y1=item.y1,
                    x2=item.x2,
                    y2=item.y2,
                    confidence=item.confidence,
                    provider=provider_name,
                )
            )

            source_image_path = resolve_source_image_path(region, problem)
            try:
                cropped_path = self.crop_service.crop_and_save(region, source_image_path)
            except (ValueError, FileNotFoundError):
                pass
            else:
                region = await self.region_repo.update(
                    region.id, ProblemRegionUpdate(cropped_image_path=cropped_path)
                ) or region

            created_regions.append(region)

        return created_regions


class FallbackRegionDetector(RegionDetector):
    """primary detector를 먼저 시도하고, 결과가 비어 있으면 fallback detector로 넘어간다.

    fallback은 실제로 필요할 때(primary가 빈 결과를 반환했을 때)만 생성한다 -
    ClaudeVisionRegionDetector처럼 생성 시점에 API 키를 요구하는 detector를
    fallback으로 쓰더라도, primary만으로 충분한 대다수 케이스에서는 그 요구사항이
    발동하지 않도록 하기 위함이다.
    """

    provider_name = "fallback-region-detector"

    def __init__(self, primary: RegionDetector, make_fallback):
        self._primary = primary
        self._make_fallback = make_fallback

    async def detect(self, problem: Problem) -> List[DetectedRegion]:
        result = await self._primary.detect(problem)
        if result:
            return result
        fallback = self._make_fallback()
        return await fallback.detect(problem)


def get_region_detector() -> RegionDetector:
    """FastAPI 의존성 기본 구현.

    PDF로 임포트된 문제는 PDFGeometryRegionDetector(PDF 자체의 임베디드 이미지/표
    좌표를 직접 읽는, 추측이 필요 없는 방식)를 먼저 시도하고, 결과가 비어 있거나
    (수동 등록 문제처럼) PDF 출처가 없으면 ClaudeVisionRegionDetector로 넘어간다.
    테스트에서는 app.dependency_overrides로 MockRegionDetector로 교체한다.
    """
    from app.services.region_detectors.claude_vision import ClaudeVisionRegionDetector
    from app.services.region_detectors.pdf_geometry import PDFGeometryRegionDetector

    return FallbackRegionDetector(PDFGeometryRegionDetector(), ClaudeVisionRegionDetector)

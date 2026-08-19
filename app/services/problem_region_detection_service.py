from typing import List

from sqlalchemy.orm import Session

from app.models.problem_region import ProblemRegion
from app.repositories.problem_region_repository import ProblemRegionRepository
from app.repositories.problem_repository import ProblemRepository
from app.schemas.problem_region_schema import ProblemRegionCreate, ProblemRegionUpdate
from app.services.problem_region_crop_service import ProblemRegionCropService, resolve_source_image_path
from app.services.region_detectors.base import RegionDetector


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
        parent_region_id = full_problem_regions[0].id if full_problem_regions else None

        detected = await self.detector.detect(image_path)
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


def get_region_detector() -> RegionDetector:
    """FastAPI 의존성 기본 구현. 테스트에서는 app.dependency_overrides로 MockRegionDetector로 교체한다."""
    from app.services.region_detectors.claude_vision import ClaudeVisionRegionDetector

    return ClaudeVisionRegionDetector()

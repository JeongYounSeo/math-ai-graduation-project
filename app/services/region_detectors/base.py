from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from app.models.problem import Problem


@dataclass
class DetectedRegion:
    """탐지된 영역 하나. region_type은 app.models.problem_region.REGION_TYPES 중 하나여야 한다."""

    region_type: str
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: Optional[float] = None
    reason: Optional[str] = None


class RegionDetector(ABC):
    """문제에서 그림/그래프/표 등의 영역을 찾는 provider 인터페이스.

    Problem 전체를 받는다 (image_path만으로는 부족한 detector가 있다 -
    예: PDF 원본의 임베디드 이미지/표 좌표를 직접 읽는 detector는
    problem.source_pdf_id/page_number/crop_box가 필요하다).
    """

    provider_name: str = "unknown"

    @abstractmethod
    async def detect(self, problem: "Problem") -> List[DetectedRegion]:
        ...

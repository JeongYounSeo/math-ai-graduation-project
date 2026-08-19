from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


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
    """문제 이미지에서 그림/그래프/표 등의 영역을 찾는 provider 인터페이스."""

    provider_name: str = "unknown"

    @abstractmethod
    async def detect(self, image_path: str) -> List[DetectedRegion]:
        ...

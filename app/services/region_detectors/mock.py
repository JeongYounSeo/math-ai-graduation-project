from pathlib import Path
from typing import List, Optional

from PIL import Image

from app.services.region_detectors.base import DetectedRegion, RegionDetector


class MockRegionDetector(RegionDetector):
    """테스트/로컬 개발용 mock detector. 실제 네트워크 호출 없이 동작한다.

    app.services.ocr_providers.mock.MockOCRProvider와 동일하게, 파일 존재 여부만
    확인하고 고정된 결과를 반환한다. 생성자로 원하는 결과를 override할 수 있다.
    """

    provider_name = "mock-region-detector"

    def __init__(self, regions: Optional[List[DetectedRegion]] = None):
        self._regions = list(regions) if regions is not None else None

    async def detect(self, image_path: str) -> List[DetectedRegion]:
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"탐지 대상 이미지가 존재하지 않습니다: {image_path}")

        if self._regions is not None:
            return list(self._regions)

        with Image.open(path) as image:
            width, height = image.size

        return [
            DetectedRegion(
                region_type="figure",
                x1=width * 0.55,
                y1=height * 0.1,
                x2=width * 0.95,
                y2=height * 0.6,
                confidence=0.6,
                reason="mock heuristic: 이미지 우측 블록을 그림으로 가정",
            )
        ]

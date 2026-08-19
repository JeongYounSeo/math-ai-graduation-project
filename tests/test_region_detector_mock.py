from pathlib import Path

import pytest
from PIL import Image

from app.services.region_detectors.base import DetectedRegion
from app.services.region_detectors.mock import MockRegionDetector


def _make_image(path: Path, size=(200, 100)) -> Path:
    Image.new("RGB", size, "white").save(path)
    return path


@pytest.mark.asyncio
async def test_detect_raises_when_image_missing(tmp_path):
    detector = MockRegionDetector()
    with pytest.raises(FileNotFoundError):
        await detector.detect(str(tmp_path / "missing.png"))


@pytest.mark.asyncio
async def test_detect_returns_default_figure_region_scaled_to_image_size(tmp_path):
    image_path = _make_image(tmp_path / "problem.png", size=(200, 100))
    detector = MockRegionDetector()

    regions = await detector.detect(str(image_path))

    assert len(regions) == 1
    region = regions[0]
    assert region.region_type == "figure"
    assert region.x1 == 200 * 0.55
    assert region.y1 == 100 * 0.1
    assert region.x2 == 200 * 0.95
    assert region.y2 == 100 * 0.6
    assert region.confidence == 0.6


@pytest.mark.asyncio
async def test_detect_returns_overridden_regions_verbatim(tmp_path):
    image_path = _make_image(tmp_path / "problem.png")
    fixed = [DetectedRegion(region_type="table", x1=1, y1=2, x2=3, y2=4, confidence=0.7, reason="fixture")]
    detector = MockRegionDetector(regions=fixed)

    regions = await detector.detect(str(image_path))

    assert regions == fixed
    assert regions is not fixed  # 복사본을 반환해야 한다

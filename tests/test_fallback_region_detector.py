import pytest

from app.models.problem import Problem
from app.services.problem_region_detection_service import FallbackRegionDetector
from app.services.region_detectors.base import DetectedRegion, RegionDetector


class _StubDetector(RegionDetector):
    def __init__(self, regions):
        self._regions = regions
        self.called = False

    async def detect(self, problem):
        self.called = True
        return self._regions


@pytest.mark.asyncio
async def test_returns_primary_result_without_calling_fallback():
    primary_regions = [DetectedRegion(region_type="figure", x1=0, y1=0, x2=1, y2=1)]
    primary = _StubDetector(primary_regions)
    fallback = _StubDetector([DetectedRegion(region_type="table", x1=0, y1=0, x2=1, y2=1)])

    detector = FallbackRegionDetector(primary, lambda: fallback)
    result = await detector.detect(Problem(id=1))

    assert result == primary_regions
    assert fallback.called is False


@pytest.mark.asyncio
async def test_falls_back_when_primary_returns_empty():
    primary = _StubDetector([])
    fallback_regions = [DetectedRegion(region_type="table", x1=0, y1=0, x2=1, y2=1)]
    fallback = _StubDetector(fallback_regions)

    detector = FallbackRegionDetector(primary, lambda: fallback)
    result = await detector.detect(Problem(id=1))

    assert result == fallback_regions
    assert fallback.called is True


@pytest.mark.asyncio
async def test_fallback_factory_not_called_when_primary_succeeds():
    primary_regions = [DetectedRegion(region_type="figure", x1=0, y1=0, x2=1, y2=1)]
    primary = _StubDetector(primary_regions)

    factory_calls = []

    def make_fallback():
        factory_calls.append(1)
        return _StubDetector([])

    detector = FallbackRegionDetector(primary, make_fallback)
    await detector.detect(Problem(id=1))

    assert factory_calls == []

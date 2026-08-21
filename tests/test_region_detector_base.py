import pytest

from app.services.region_detectors.base import DetectedRegion, RegionDetector


def test_detected_region_holds_fields():
    region = DetectedRegion(region_type="figure", x1=1.0, y1=2.0, x2=3.0, y2=4.0, confidence=0.9, reason="test")
    assert region.region_type == "figure"
    assert region.x1 == 1.0
    assert region.confidence == 0.9
    assert region.reason == "test"


def test_region_detector_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        RegionDetector()


def test_region_detector_provider_name_defaults_to_unknown():
    assert RegionDetector.provider_name == "unknown"

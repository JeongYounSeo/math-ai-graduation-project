import pytest

from app.services.region_detectors.claude_vision import _parse_detected_region


def test_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    from app.services.region_detectors.claude_vision import ClaudeVisionRegionDetector

    with pytest.raises(ValueError):
        ClaudeVisionRegionDetector()


class TestParseDetectedRegion:
    """_parse_detected_region 함수의 좌표 파싱 테스트"""

    def test_parses_valid_region(self):
        """유효한 region item을 파싱합니다."""
        item = {
            "region_type": "figure",
            "x1": 10,
            "y1": 20,
            "x2": 100,
            "y2": 200,
            "confidence": 0.95,
            "reason": "수학 그림",
        }
        region = _parse_detected_region(item)
        assert region.region_type == "figure"
        assert region.x1 == 10.0
        assert region.y1 == 20.0
        assert region.x2 == 100.0
        assert region.y2 == 200.0
        assert region.confidence == 0.95
        assert region.reason == "수학 그림"

    def test_missing_x1_raises_value_error(self):
        """x1이 없으면 ValueError를 던집니다."""
        item = {
            "region_type": "figure",
            "y1": 20,
            "x2": 100,
            "y2": 200,
        }
        with pytest.raises(ValueError, match="region 좌표가 올바르지 않습니다"):
            _parse_detected_region(item)

    def test_missing_y1_raises_value_error(self):
        """y1이 없으면 ValueError를 던집니다."""
        item = {
            "region_type": "figure",
            "x1": 10,
            "x2": 100,
            "y2": 200,
        }
        with pytest.raises(ValueError, match="region 좌표가 올바르지 않습니다"):
            _parse_detected_region(item)

    def test_missing_x2_raises_value_error(self):
        """x2가 없으면 ValueError를 던집니다."""
        item = {
            "region_type": "figure",
            "x1": 10,
            "y1": 20,
            "y2": 200,
        }
        with pytest.raises(ValueError, match="region 좌표가 올바르지 않습니다"):
            _parse_detected_region(item)

    def test_missing_y2_raises_value_error(self):
        """y2가 없으면 ValueError를 던집니다."""
        item = {
            "region_type": "figure",
            "x1": 10,
            "y1": 20,
            "x2": 100,
        }
        with pytest.raises(ValueError, match="region 좌표가 올바르지 않습니다"):
            _parse_detected_region(item)

    def test_non_numeric_x1_raises_value_error(self):
        """x1이 숫자가 아니면 ValueError를 던집니다."""
        item = {
            "region_type": "figure",
            "x1": "invalid",
            "y1": 20,
            "x2": 100,
            "y2": 200,
        }
        with pytest.raises(ValueError, match="region 좌표가 올바르지 않습니다"):
            _parse_detected_region(item)

    def test_non_numeric_y1_raises_value_error(self):
        """y1이 숫자가 아니면 ValueError를 던집니다."""
        item = {
            "region_type": "figure",
            "x1": 10,
            "y1": "invalid",
            "x2": 100,
            "y2": 200,
        }
        with pytest.raises(ValueError, match="region 좌표가 올바르지 않습니다"):
            _parse_detected_region(item)

    def test_non_numeric_x2_raises_value_error(self):
        """x2가 숫자가 아니면 ValueError를 던집니다."""
        item = {
            "region_type": "figure",
            "x1": 10,
            "y1": 20,
            "x2": "invalid",
            "y2": 200,
        }
        with pytest.raises(ValueError, match="region 좌표가 올바르지 않습니다"):
            _parse_detected_region(item)

    def test_non_numeric_y2_raises_value_error(self):
        """y2가 숫자가 아니면 ValueError를 던집니다."""
        item = {
            "region_type": "figure",
            "x1": 10,
            "y1": 20,
            "x2": 100,
            "y2": "invalid",
        }
        with pytest.raises(ValueError, match="region 좌표가 올바르지 않습니다"):
            _parse_detected_region(item)

    def test_non_dict_item_raises_value_error(self):
        """region 항목이 dict가 아니면 ValueError를 던집니다 (AttributeError/TypeError 아님)."""
        with pytest.raises(ValueError, match="region 항목이 올바르지 않습니다"):
            _parse_detected_region("figure")

    def test_invalid_region_type_raises_value_error(self):
        """허용되지 않은 region_type은 ValueError를 던집니다."""
        item = {
            "region_type": "invalid_type",
            "x1": 10,
            "y1": 20,
            "x2": 100,
            "y2": 200,
        }
        with pytest.raises(ValueError, match="허용되지 않은 region_type"):
            _parse_detected_region(item)

    def test_string_coordinates_converted_to_float(self):
        """문자열 숫자는 float로 변환됩니다."""
        item = {
            "region_type": "graph",
            "x1": "10.5",
            "y1": "20.5",
            "x2": "100.5",
            "y2": "200.5",
        }
        region = _parse_detected_region(item)
        assert region.x1 == 10.5
        assert region.y1 == 20.5
        assert region.x2 == 100.5
        assert region.y2 == 200.5

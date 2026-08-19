import pytest


def test_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    from app.services.region_detectors.claude_vision import ClaudeVisionRegionDetector

    with pytest.raises(ValueError):
        ClaudeVisionRegionDetector()

"""TASK 1.4 — Claude 설정 프로퍼티 단위/예시 테스트.

Settings의 프로퍼티는 os.getenv를 @property 안에서 매번 읽으므로, 환경변수를
monkeypatch로 바꾼 뒤 새 Settings()를 인스턴스화하면 최신 값을 즉시 반영한다
(reload 불필요).

Requirements: 6.2, 6.3, 13.1, 13.2, 13.3
"""

from app.core.config import Settings


def _clear_claude_env(monkeypatch):
    """세 관련 환경변수를 모두 제거해 결정론적 시작 상태를 만든다."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_VISION_MODEL", raising=False)


def test_only_anthropic_key_set_uses_anthropic(monkeypatch):
    _clear_claude_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-value")

    settings = Settings()

    assert settings.ANTHROPIC_API_KEY == "anthropic-value"


def test_only_claude_key_set_falls_back_to_claude(monkeypatch):
    _clear_claude_env(monkeypatch)
    monkeypatch.setenv("CLAUDE_API_KEY", "claude-value")

    settings = Settings()

    # ANTHROPIC_API_KEY 미설정 시 CLAUDE_API_KEY 값으로 폴백한다(Req 6.2, 13.2).
    assert settings.ANTHROPIC_API_KEY == "claude-value"


def test_both_keys_set_anthropic_wins(monkeypatch):
    _clear_claude_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-value")
    monkeypatch.setenv("CLAUDE_API_KEY", "claude-value")

    settings = Settings()

    # 둘 다 설정 시 ANTHROPIC_API_KEY 우선(Req 6.3, 13.2).
    assert settings.ANTHROPIC_API_KEY == "anthropic-value"


def test_neither_key_set_returns_none(monkeypatch):
    _clear_claude_env(monkeypatch)

    settings = Settings()

    # 둘 다 없으면 None(Req 13.1).
    assert settings.ANTHROPIC_API_KEY is None


def test_vision_model_default_is_nonempty_when_unset(monkeypatch):
    _clear_claude_env(monkeypatch)

    settings = Settings()
    model = settings.CLAUDE_VISION_MODEL

    # 환경변수 미설정 시 비어 있지 않은 기본 모델명 반환(Req 13.3).
    assert isinstance(model, str)
    assert model.strip() != ""


def test_vision_model_env_override(monkeypatch):
    _clear_claude_env(monkeypatch)
    monkeypatch.setenv("CLAUDE_VISION_MODEL", "custom-vision-model")

    settings = Settings()

    # 환경변수 설정 시 그 값을 그대로 반환(Req 13.3).
    assert settings.CLAUDE_VISION_MODEL == "custom-vision-model"

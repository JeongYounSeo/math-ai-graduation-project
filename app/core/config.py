import os
from pathlib import Path
from typing import Optional

# .env 파일을 로드한다. python-dotenv가 설치되어 있으면 프로젝트 루트의 .env를
# 읽어 os.environ에 채운다. 미설치 시에도 앱이 죽지 않도록 안전하게 무시하며,
# 이 경우 실제 OS 환경변수만 사용된다.
try:
    from dotenv import load_dotenv

    # config.py -> app/core/config.py 이므로 parents[2]가 프로젝트 루트.
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    load_dotenv(_PROJECT_ROOT / ".env")
except Exception:
    # dotenv 미설치 또는 로드 실패 시 OS 환경변수로만 동작한다.
    pass


class Settings:
    @property
    def DATABASE_URL(self) -> str:
        return os.getenv("DATABASE_URL", "sqlite:///./math_problem_engine.db")

    @property
    def OPENAI_API_KEY(self) -> Optional[str]:
        return os.getenv("OPENAI_API_KEY")

    @property
    def ANTHROPIC_API_KEY(self) -> Optional[str]:
        return os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")

    @property
    def CLAUDE_VISION_MODEL(self) -> str:
        return os.getenv("CLAUDE_VISION_MODEL", "claude-sonnet-4-6")

    @property
    def GEMINI_API_KEY(self) -> Optional[str]:
        return os.getenv("GEMINI_API_KEY")

    @property
    def GEMINI_CROP_MODEL(self) -> str:
        return os.getenv("GEMINI_CROP_MODEL", "gemini-3.1-flash-lite")

    @property
    def DEBUG(self) -> bool:
        return os.getenv("DEBUG", "False").lower() == "true"

    @property
    def ENABLE_REGION_OVERLAP_VALIDATION(self) -> bool:
        # 겹침 검증 훅 gating 플래그(설계 §7). 기본 False → 기존 crop 파이프라인과
        # 100% 동일(회귀 0). "true"(대소문자 무관)일 때만 훅을 활성화한다.
        return os.getenv("ENABLE_REGION_OVERLAP_VALIDATION", "False").lower() == "true"


settings = Settings()

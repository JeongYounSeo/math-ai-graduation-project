import os
from typing import Optional


class Settings:
    @property
    def DATABASE_URL(self) -> str:
        return os.getenv("DATABASE_URL", "sqlite:///./math_problem_engine.db")

    @property
    def OPENAI_API_KEY(self) -> Optional[str]:
        return os.getenv("OPENAI_API_KEY")

    @property
    def DEBUG(self) -> bool:
        return os.getenv("DEBUG", "False").lower() == "true"


settings = Settings()
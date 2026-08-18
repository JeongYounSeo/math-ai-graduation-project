import base64
import json
from pathlib import Path

from app.core.config import settings
from app.services.ocr_providers.base import OCRProvider, OCRResult

_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

_PROMPT = (
    "다음은 수학 문제 이미지입니다. 문제 본문과, 객관식이라면 보기 목록을 추출해서 "
    "아래 JSON 형식으로만 응답하세요. JSON 앞뒤로 다른 설명을 붙이지 마세요.\n\n"
    '{"body_text": "문제 본문 전체", "choices": ["보기1", "보기2", ...], "latex_text": "수식이 있다면 LaTeX 표현"}\n\n'
    "객관식이 아니면 choices는 빈 배열 []로 두세요. "
    "수식이 없거나 확신할 수 없으면 latex_text는 null로 두세요. "
    "이 문제의 정답이 무엇인지는 절대 판단하거나 응답에 포함하지 마세요."
)


class ClaudeVisionOCRProvider(OCRProvider):
    """Claude vision API로 문제 이미지에서 본문/보기 텍스트를 추출하는 provider.

    app.core.config.settings.ANTHROPIC_API_KEY가 설정되어 있지 않으면
    생성 시점에 바로 에러를 낸다 (조용히 실패하거나 가짜 데이터를 반환하지 않는다).
    """

    def __init__(self, model: str = "claude-sonnet-4-5-20250929"):
        api_key = settings.ANTHROPIC_API_KEY
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY가 설정되어 있지 않습니다. "
                "환경변수 ANTHROPIC_API_KEY를 설정한 뒤 다시 시도하세요."
            )

        import anthropic

        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def extract(self, image_path: str) -> OCRResult:
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"OCR 대상 이미지가 존재하지 않습니다: {image_path}")

        media_type = _MIME_TYPES.get(path.suffix.lower(), "image/png")
        image_b64 = base64.b64encode(path.read_bytes()).decode("ascii")

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": media_type, "data": image_b64},
                        },
                        {"type": "text", "text": _PROMPT},
                    ],
                }
            ],
        )

        raw_text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )

        try:
            parsed = json.loads(_extract_json_object(raw_text))
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"OCR 응답을 JSON으로 파싱할 수 없습니다: {raw_text!r}") from exc

        choices = parsed.get("choices") or []
        if not isinstance(choices, list):
            raise ValueError(f"OCR 응답의 choices가 리스트가 아닙니다: {choices!r}")

        return OCRResult(
            body_text=parsed.get("body_text"),
            choices=[str(choice) for choice in choices],
            latex_text=parsed.get("latex_text"),
            confidence=None,
            provider_name="claude-vision",
        )


def _extract_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("응답에서 JSON 객체를 찾을 수 없습니다.")
    return text[start : end + 1]

import base64
import json
from pathlib import Path
from typing import List

from PIL import Image

from app.core.config import settings
from app.services.region_detectors.base import DetectedRegion, RegionDetector

_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

_ALLOWED_REGION_TYPES = {"figure", "graph", "table"}


class ClaudeVisionRegionDetector(RegionDetector):
    """Claude vision API로 문제 이미지 안의 그림/그래프/표 영역을 찾는 detector.

    app.core.config.settings.ANTHROPIC_API_KEY가 설정되어 있지 않으면
    생성 시점에 바로 에러를 낸다 (조용히 실패하거나 가짜 데이터를 반환하지 않는다).
    """

    provider_name = "claude-vision-region-detector"

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

    async def detect(self, image_path: str) -> List[DetectedRegion]:
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"탐지 대상 이미지가 존재하지 않습니다: {image_path}")

        with Image.open(path) as image:
            width, height = image.size

        media_type = _MIME_TYPES.get(path.suffix.lower(), "image/png")
        image_b64 = base64.b64encode(path.read_bytes()).decode("ascii")

        prompt = (
            f"다음은 가로 {width}px, 세로 {height}px 크기의 수학 문제 이미지입니다. "
            "이미지 안에 그림, 그래프, 표가 있는지 찾아서 각각의 픽셀 좌표 bounding box를 "
            "아래 JSON 형식으로만 응답하세요. JSON 앞뒤로 다른 설명을 붙이지 마세요.\n\n"
            '{"regions": [{"region_type": "figure|graph|table", "x1": 0, "y1": 0, "x2": 0, "y2": 0, '
            '"confidence": 0.0, "reason": "판단 근거"}]}\n\n'
            "region_type은 반드시 figure, graph, table 중 하나여야 합니다. "
            "좌표는 이미지 왼쪽 위를 (0,0)으로 하는 픽셀 단위입니다. "
            "그림/그래프/표가 하나도 없으면 regions를 빈 배열 []로 두세요. "
            "이 문제의 정답이 무엇인지는 절대 판단하거나 응답에 포함하지 마세요."
        )

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
                        {"type": "text", "text": prompt},
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
            raise ValueError(f"탐지 응답을 JSON으로 파싱할 수 없습니다: {raw_text!r}") from exc

        regions = parsed.get("regions")
        if not isinstance(regions, list):
            raise ValueError(f"탐지 응답의 regions가 리스트가 아닙니다: {regions!r}")

        detected = []
        for item in regions:
            region_type = item.get("region_type")
            if region_type not in _ALLOWED_REGION_TYPES:
                raise ValueError(f"허용되지 않은 region_type입니다: {region_type!r}")
            detected.append(
                DetectedRegion(
                    region_type=region_type,
                    x1=float(item["x1"]),
                    y1=float(item["y1"]),
                    x2=float(item["x2"]),
                    y2=float(item["y2"]),
                    confidence=item.get("confidence"),
                    reason=item.get("reason"),
                )
            )
        return detected


def _extract_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("응답에서 JSON 객체를 찾을 수 없습니다.")
    return text[start : end + 1]

import base64
import json
from pathlib import Path
from typing import List

from PIL import Image

from app.core.config import settings
from app.models.problem import Problem
from app.services.region_detectors.base import DetectedRegion, RegionDetector

_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

_ALLOWED_REGION_TYPES = {"figure", "graph", "table"}


def _parse_detected_region(item: dict, image_width: float, image_height: float) -> DetectedRegion:
    """단일 탐지 결과 item을 DetectedRegion으로 파싱합니다.

    모델은 좌표를 이미지 크기와 무관한 0~1000 상대 스케일로 반환한다
    (비전 모델은 원본 픽셀 크기가 큰 이미지에서 절대 픽셀 좌표를 정확히
    맞히지 못하는 경우가 많아, 0~1000 상대 좌표로 받은 뒤 여기서 직접
    실제 픽셀 좌표로 환산한다). 범위를 벗어난 값은 0~1000으로 clamp한다.

    좌표가 누락되거나 올바르지 않으면 ValueError를 던집니다.
    """
    if not isinstance(item, dict):
        raise ValueError(f"탐지 응답의 region 항목이 올바르지 않습니다: {item!r}")

    region_type = item.get("region_type")
    if region_type not in _ALLOWED_REGION_TYPES:
        raise ValueError(f"허용되지 않은 region_type입니다: {region_type!r}")

    try:
        x1_norm = float(item["x1"])
        y1_norm = float(item["y1"])
        x2_norm = float(item["x2"])
        y2_norm = float(item["y2"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"탐지 응답의 region 좌표가 올바르지 않습니다: {item!r}"
        ) from exc

    x1_norm, y1_norm, x2_norm, y2_norm = (
        _clamp(x1_norm), _clamp(y1_norm), _clamp(x2_norm), _clamp(y2_norm)
    )

    return DetectedRegion(
        region_type=region_type,
        x1=x1_norm / 1000.0 * image_width,
        y1=y1_norm / 1000.0 * image_height,
        x2=x2_norm / 1000.0 * image_width,
        y2=y2_norm / 1000.0 * image_height,
        confidence=item.get("confidence"),
        reason=item.get("reason"),
    )


def _clamp(value: float, low: float = 0.0, high: float = 1000.0) -> float:
    return max(low, min(high, value))


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

    async def detect(self, problem: Problem) -> List[DetectedRegion]:
        image_path = problem.problem_image_path or problem.page_image_path
        if not image_path:
            raise ValueError("탐지를 실행할 이미지가 없습니다")
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"탐지 대상 이미지가 존재하지 않습니다: {image_path}")

        with Image.open(path) as image:
            width, height = image.size

        media_type = _MIME_TYPES.get(path.suffix.lower(), "image/png")
        image_b64 = base64.b64encode(path.read_bytes()).decode("ascii")

        prompt = (
            "다음은 수학 문제 이미지입니다. 이미지 안에 그림, 그래프, 표가 있는지 찾아서 "
            "각 영역의 위치를 아래 JSON 형식으로만 응답하세요. JSON 앞뒤로 다른 설명을 붙이지 마세요.\n\n"
            '{"regions": [{"reason": "이 영역이 그림/그래프/표라고 판단한 근거와 이미지 안에서의 '
            '대략적인 위치를 먼저 설명", "region_type": "figure|graph|table", '
            '"x1": 0, "y1": 0, "x2": 0, "y2": 0, "confidence": 0.0}]}\n\n'
            "각 항목은 위 순서(reason을 먼저, 좌표는 나중에) 그대로 작성해서, 좌표를 정하기 전에 "
            "먼저 위치를 말로 설명하고 판단하세요.\n\n"
            "좌표는 실제 픽셀 값이 아니라, 이미지 왼쪽 위를 (0,0), 오른쪽 아래를 (1000,1000)으로 "
            "하는 0~1000 사이의 상대 좌표입니다 (예: 이미지 정중앙은 (500,500), 이미지 하단 절반 "
            "전체 너비를 덮는 영역이면 x1=0, y1=500, x2=1000, y2=1000). 실제 픽셀 크기는 신경 쓰지 "
            "말고 이미지 전체 대비 비율로만 판단하세요.\n\n"
            "region_type은 반드시 figure, graph, table 중 하나여야 합니다. "
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
            detected.append(_parse_detected_region(item, width, height))
        return detected


def _extract_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("응답에서 JSON 객체를 찾을 수 없습니다.")
    return text[start : end + 1]

"""영역 추출 테스트용 임포트 가능한 헬퍼와 Hypothesis 전략.

이 모듈은 pytest 픽스처를 포함하지 않는다(순수 함수/전략만 제공). 그래야 속성
기반 테스트에서 자유롭게 import 해 재사용할 수 있다. import 시점에 부작용이
없도록 유지한다.
"""

from hypothesis import strategies as st

from app.services.claude_vision_client import VisionCallResult

# region_type 이 가질 수 있는 6가지 값.
REGION_TYPES = (
    "QUESTION_TEXT",
    "DIAGRAM",
    "CHOICE_BOX",
    "STATEMENT_BOX",
    "TABLE",
    "OTHER",
)

# 라벨 문자 집합.
CHOICE_LABELS = ("①", "②", "③", "④", "⑤")
STATEMENT_LABELS = ("ㄱ", "ㄴ", "ㄷ")


# ---------------------------------------------------------------------------
# 대표 JSON 응답 빌더
# ---------------------------------------------------------------------------
def make_vision_success_json() -> dict:
    """유효한 구조화 응답(regions 리스트 포함)을 반환한다."""
    return {
        "regions": [
            {
                "region_type": "QUESTION_TEXT",
                "bounding_box": {"left": 10, "top": 10, "right": 500, "bottom": 120},
                "ocr_text": "다음 함수의 최댓값을 구하시오.",
                "latex_text": "다음 함수 $f(x) = x^2 + 1$ 의 최댓값을 구하시오.",
                "confidence": 0.95,
            },
            {
                "region_type": "DIAGRAM",
                "bounding_box": {"left": 10, "top": 130, "right": 300, "bottom": 400},
                "ocr_text": None,
                "latex_text": None,
                "confidence": 0.88,
            },
            {
                "region_type": "CHOICE_BOX",
                "bounding_box": {"left": 10, "top": 410, "right": 500, "bottom": 700},
                "ocr_text": None,
                "latex_text": None,
                "confidence": 0.9,
                "items": [
                    {
                        "label": label,
                        "text": f"보기 {idx + 1}",
                        "latex": f"${idx + 1}$",
                        "is_image": False,
                    }
                    for idx, label in enumerate(CHOICE_LABELS)
                ],
            },
            {
                "region_type": "STATEMENT_BOX",
                "bounding_box": {"left": 10, "top": 710, "right": 500, "bottom": 900},
                "ocr_text": None,
                "latex_text": None,
                "confidence": 0.82,
                "items": [
                    {
                        "label": label,
                        "text": f"명제 {label}",
                        "latex": "",
                        "is_image": False,
                    }
                    for label in STATEMENT_LABELS
                ],
            },
        ]
    }


def make_vision_malformed() -> dict:
    """`regions` 리스트가 없는 malformed 응답을 반환한다."""
    return {"foo": 1}


def make_vision_empty() -> dict:
    """영역이 하나도 없는 유효 응답을 반환한다."""
    return {"regions": []}


# ---------------------------------------------------------------------------
# Vision 클라이언트 테스트 더블
# ---------------------------------------------------------------------------
class FakeVisionClient:
    """네트워크 없이 결정론적 결과를 반환하는 ClaudeVisionClient 대체품.

    - raw_json 이 주어지면 성공 결과로 감싸 반환한다.
    - result(VisionCallResult)가 주어지면 그대로 반환한다.
    - 둘 다 없으면 빈 성공 결과를 반환한다.
    호출할 때마다 call_count 를 증가시켜(정상 시 이미지당 1회) 호출 횟수를
    검증할 수 있게 한다.
    """

    def __init__(self, result=None, raw_json=None, configured=True):
        self._result = result
        self._raw_json = raw_json
        self._configured = configured
        self.call_count = 0

    def is_configured(self) -> bool:
        return self._configured

    def extract(self, image_path, prompt) -> VisionCallResult:
        self.call_count += 1
        if self._raw_json is not None:
            return VisionCallResult(
                success=True,
                raw_json=self._raw_json,
                failure_type=None,
                error_message=None,
            )
        if self._result is not None:
            return self._result
        return VisionCallResult(
            success=True,
            raw_json={"regions": []},
            failure_type=None,
            error_message=None,
        )


# ---------------------------------------------------------------------------
# Hypothesis 전략
# ---------------------------------------------------------------------------
def bounding_box_strategy():
    """left<right, top<bottom 을 보장하는 바운딩 박스 전략."""

    def _build(left, top, width, height):
        return {
            "left": left,
            "top": top,
            "right": left + width,
            "bottom": top + height,
        }

    return st.builds(
        _build,
        left=st.integers(min_value=0, max_value=2000),
        top=st.integers(min_value=0, max_value=2000),
        width=st.integers(min_value=1, max_value=2000),
        height=st.integers(min_value=1, max_value=2000),
    )


def _text_or_none():
    return st.one_of(st.none(), st.text(max_size=40))


def _confidence_strategy():
    """None, 정상 범위(0.0~1.0), 범위 밖(-0.5, 1.5)을 모두 포함한다."""
    return st.one_of(
        st.none(),
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        st.sampled_from([-0.5, 1.5]),
    )


def _label_strategy():
    return st.sampled_from(CHOICE_LABELS + STATEMENT_LABELS)


def labeled_items_strategy():
    """항목 중심 속성 테스트용: 1~10개의 항목 dict 리스트."""
    item = st.fixed_dictionaries(
        {
            "label": _label_strategy(),
            "text": _text_or_none(),
            "latex": _text_or_none(),
            "is_image": st.booleans(),
        }
    )
    return st.lists(item, min_size=1, max_size=10)


def region_json_strategy():
    """무작위 유효 region dict 전략.

    CHOICE_BOX/STATEMENT_BOX 인 경우에만 items 리스트를 포함한다.
    """

    def _build(region_type, bbox, ocr_text, latex_text, confidence, items):
        region = {
            "region_type": region_type,
            "bounding_box": bbox,
            "ocr_text": ocr_text,
            "latex_text": latex_text,
            "confidence": confidence,
        }
        if region_type in ("CHOICE_BOX", "STATEMENT_BOX"):
            region["items"] = items
        return region

    return st.builds(
        _build,
        region_type=st.sampled_from(REGION_TYPES),
        bbox=bounding_box_strategy(),
        ocr_text=_text_or_none(),
        latex_text=_text_or_none(),
        confidence=_confidence_strategy(),
        items=labeled_items_strategy(),
    )


def regions_response_strategy():
    """{"regions": [...]} 형태의 응답 전략(최대 8개 영역)."""
    return st.fixed_dictionaries(
        {"regions": st.lists(region_json_strategy(), max_size=8)}
    )

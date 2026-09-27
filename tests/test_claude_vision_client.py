"""`ClaudeVisionClient` 단위/예시 테스트 및 재시도 상한·백오프 속성 테스트.

- Task 7.4: 실패 유형별 예시 테스트(성공/ malformed / 재시도 분류 / 미설정 / 이미지 읽기 불가).
- Task 7.3: Property 11 (재시도 상한 + 백오프 [1,30]) 속성 기반 테스트.

네트워크 차단 기법:
`ClaudeVisionClient`는 `_get_client()`에서 `self._client is None`일 때만 `anthropic`
SDK를 import한다. 따라서 `extract()` 호출 전에 `client._client`를 가짜 SDK 객체로
설정하면 SDK import 및 실제 네트워크 호출이 전부 우회된다. 가짜 SDK는
`.messages.create(model, max_tokens, messages)` 메서드만 제공하면 된다. 성공 응답
객체는 `content`가 각 블록에 `.text`를 갖는 리스트여야 한다(클라이언트의
`_extract_response_text` 규약).

`tests/conftest.py`의 autouse 네트워크 가드가 루프백이 아닌 소켓 연결을 차단하므로,
가짜 SDK로 대체하면 어떤 실제 요청도 발생하지 않는다.
"""

import types

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from PIL import Image

import app.services.claude_vision_client as cvc
from app.services.claude_vision_client import (
    FAILURE_IMAGE_UNREADABLE,
    FAILURE_MALFORMED,
    FAILURE_NOT_CONFIGURED,
    FAILURE_RATE_LIMITED,
    FAILURE_SERVER_ERROR,
    FAILURE_TIMEOUT,
    ClaudeVisionClient,
    VisionCallResult,
)


# ---------------------------------------------------------------------------
# 테스트 헬퍼: 가짜 SDK 및 응답 빌더
# ---------------------------------------------------------------------------


def _make_valid_png(tmp_path, name="problem.png"):
    """실제로 열 수 있는 작은 PNG를 생성하고 경로 문자열을 반환한다."""
    path = tmp_path / name
    Image.new("RGB", (10, 10), color=(255, 255, 255)).save(str(path))
    return str(path)


def _success_response(text):
    """`_extract_response_text`가 파싱할 수 있는 응답 객체를 만든다."""
    return types.SimpleNamespace(content=[types.SimpleNamespace(text=text)])


class _FakeMessages:
    """`messages.create(...)`를 흉내내는 객체. 호출 횟수를 기록한다."""

    def __init__(self, *, response=None, exc=None):
        self._response = response
        self._exc = exc
        self.call_count = 0
        self.last_kwargs = None

    def create(self, model, max_tokens, messages):
        self.call_count += 1
        self.last_kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if self._exc is not None:
            raise self._exc
        return self._response


class _FakeSDK:
    """`client.messages.create(...)` 구조를 흉내내는 가짜 SDK 클라이언트."""

    def __init__(self, *, response=None, exc=None):
        self.messages = _FakeMessages(response=response, exc=exc)


def _make_status_exc(status_code):
    """`status_code` 속성을 가진 예외 인스턴스(상태 코드 기반 분류용)."""
    exc = RuntimeError(f"status {status_code}")
    exc.status_code = status_code
    return exc


class FakeTimeout(Exception):
    """클래스명 기반 폴백 분류('timeout' in name)를 유발하는 예외."""


# ---------------------------------------------------------------------------
# Task 7.4: 예시 테스트
# ---------------------------------------------------------------------------


def test_extract_success_returns_parsed_json_single_call(tmp_path):
    """유효 JSON 응답 시 success=True, raw_json 파싱, 호출 정확히 1회."""
    png = _make_valid_png(tmp_path)
    fake = _FakeSDK(response=_success_response('{"regions": []}'))
    client = ClaudeVisionClient(api_key="k", model="m", max_retries=2)
    client._client = fake  # SDK import/네트워크 우회

    result = client.extract(png, "prompt")

    assert isinstance(result, VisionCallResult)
    assert result.success is True
    assert result.raw_json == {"regions": []}
    assert result.failure_type is None
    assert result.error_message is None
    assert fake.messages.call_count == 1


def test_extract_malformed_response_maps_to_malformed(tmp_path):
    """JSON으로 파싱할 수 없는 응답은 failure_type=malformed."""
    png = _make_valid_png(tmp_path)
    fake = _FakeSDK(response=_success_response("not json {{{"))
    client = ClaudeVisionClient(api_key="k", model="m", max_retries=2)
    client._client = fake

    result = client.extract(png, "prompt")

    assert result.success is False
    assert result.failure_type == FAILURE_MALFORMED
    assert result.raw_json is None
    # 성공 응답을 받았으므로(파싱만 실패) 재시도하지 않고 1회 호출.
    assert fake.messages.call_count == 1


@pytest.mark.parametrize(
    "exc_factory,expected",
    [
        (lambda: _make_status_exc(429), FAILURE_RATE_LIMITED),
        (lambda: _make_status_exc(500), FAILURE_SERVER_ERROR),
        (lambda: FakeTimeout("boom"), FAILURE_TIMEOUT),
    ],
)
def test_extract_retryable_exception_classification(
    tmp_path, monkeypatch, exc_factory, expected
):
    """재시도 대상 예외가 올바른 failure_type으로 분류된다.

    max_retries=0 이므로 단일 호출 후 즉시 실패를 반환한다(재시도 없음).
    """
    # 백오프 대기를 무력화(안전 차원, max_retries=0이면 호출되지 않음).
    monkeypatch.setattr(cvc.time, "sleep", lambda *_a, **_k: None)

    png = _make_valid_png(tmp_path)
    fake = _FakeSDK(exc=exc_factory())
    client = ClaudeVisionClient(api_key="k", model="m", max_retries=0)
    client._client = fake

    result = client.extract(png, "prompt")

    assert result.success is False
    assert result.failure_type == expected
    assert result.raw_json is None
    assert fake.messages.call_count == 1


def test_extract_not_configured_sends_no_request(tmp_path):
    """자격증명 부재 시 SDK를 구성하지 않고 미설정 오류 반환."""
    png = _make_valid_png(tmp_path)
    client = ClaudeVisionClient(api_key=None, model="m")

    assert client.is_configured() is False

    result = client.extract(png, "prompt")

    assert result.success is False
    assert result.failure_type == FAILURE_NOT_CONFIGURED
    assert result.raw_json is None
    # SDK 클라이언트가 절대 생성되지 않았음(네트워크 시도 없음).
    assert client._client is None


def test_empty_api_key_is_not_configured():
    """빈 문자열 api_key도 미설정으로 간주된다."""
    client = ClaudeVisionClient(api_key="", model="m")
    assert client.is_configured() is False


def test_extract_unreadable_image_returns_error_without_call(tmp_path):
    """이미지 읽기 불가 시 failure_type=image_unreadable, SDK 호출 없음."""
    missing = str(tmp_path / "nope.png")
    fake = _FakeSDK(response=_success_response('{"regions": []}'))
    client = ClaudeVisionClient(api_key="k", model="m")
    client._client = fake

    result = client.extract(missing, "prompt")

    assert result.success is False
    assert result.failure_type == FAILURE_IMAGE_UNREADABLE
    assert result.raw_json is None
    # 인코딩이 먼저 실패하므로 SDK는 호출되지 않는다.
    assert fake.messages.call_count == 0


# ---------------------------------------------------------------------------
# Task 7.3: Property 11 (재시도 상한 + 백오프 범위)
# ---------------------------------------------------------------------------


def test_property_retry_bounded_and_backoff_within_range(tmp_path):
    """재시도는 상한(원본+max_retries)을 지키고 백오프는 [1, 30]초 범위 안이다."""
    png = _make_valid_png(tmp_path)

    # @given 내부에서 함수 스코프 fixture를 쓰면 hypothesis 헬스체크에 걸리므로,
    # time.sleep은 @given 바깥에서 한 번 패치하고 finally에서 복원한다.
    recorded = []
    orig_sleep = cvc.time.sleep
    cvc.time.sleep = lambda seconds: recorded.append(seconds)
    try:

        # Feature: problem-region-vision-ocr, Property 11: 재시도는 상한과 백오프 범위를 지킨다
        @settings(max_examples=100)
        @given(
            status_code=st.sampled_from([429, 500, 503]),
            max_retries=st.integers(min_value=0, max_value=2),
        )
        def check(status_code, max_retries):
            recorded.clear()
            fake = _FakeSDK(exc=_make_status_exc(status_code))
            client = ClaudeVisionClient(
                api_key="k", model="m", max_retries=max_retries
            )
            client._client = fake

            result = client.extract(png, "prompt")

            # 항상 실패하는 재시도 대상 → 재시도를 모두 소진.
            assert result.success is False
            # 총 호출 = 원본 1회 + 재시도 max_retries회.
            assert fake.messages.call_count == max_retries + 1
            assert fake.messages.call_count <= 3
            # 대기 횟수 = 재시도 횟수.
            assert len(recorded) == max_retries
            # 각 대기는 1초 이상 30초 이하.
            for wait in recorded:
                assert 1.0 <= wait <= 30.0

        check()
    finally:
        cvc.time.sleep = orig_sleep

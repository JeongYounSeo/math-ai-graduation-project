"""Thin wrapper around the Anthropic Claude Vision SDK.

This module separates orchestration (service) logic from network / retry /
timeout / JSON-parsing concerns. Tests mock only this class's extract() (or the
inner SDK call) to block all network access (Req 15).

The anthropic SDK is imported lazily so this module imports fine even when the
dependency is not installed; the SDK is loaded only at actual call time.
"""

import base64
import json
import logging
import mimetypes
import os
import random
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# extract() result failure_type values.
FAILURE_TIMEOUT = "timeout"
FAILURE_RATE_LIMITED = "rate_limited"
FAILURE_SERVER_ERROR = "server_error"
FAILURE_MALFORMED = "malformed"
FAILURE_NOT_CONFIGURED = "not_configured"
FAILURE_IMAGE_UNREADABLE = "image_unreadable"
# Environment/config problem such as the SDK not being installed. Retrying cannot
# succeed, so this is NOT a retryable failure type.
FAILURE_DEPENDENCY_MISSING = "dependency_missing"

# Retryable failure types.
_RETRYABLE_FAILURES = frozenset(
    {FAILURE_TIMEOUT, FAILURE_RATE_LIMITED, FAILURE_SERVER_ERROR}
)


@dataclass
class VisionCallResult:
    """Result of a single Vision call.

    - success: whether the call and JSON parsing succeeded
    - raw_json: parsed structured JSON (dict) on success, else None
    - failure_type: failure kind
    - error_message: human-readable error description (None on success)
    """

    success: bool
    raw_json: Optional[dict]
    failure_type: Optional[str]
    error_message: Optional[str]


class ClaudeVisionClient:
    """Single-call wrapper that takes an image + prompt and returns structured JSON.

    Handles timeout (default 60s), retries (up to 2, waiting 1-30s before each),
    and credential checking.
    """

    def __init__(
        self,
        api_key: Optional[str],
        model: str,
        timeout_seconds: int = 60,
        max_retries: int = 2,
    ):
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        # The SDK client is created lazily on first call.
        self._client = None

    def is_configured(self) -> bool:
        """Whether credentials exist. If not, the service falls back to the stub (Req 6)."""
        return bool(self.api_key)

    def _get_client(self):
        """Lazily create the anthropic SDK client.

        If the SDK is not installed, ImportError propagates.
        """
        if self._client is None:
            import anthropic  # lazy import (safe when dependency is missing)

            self._client = anthropic.Anthropic(
                api_key=self.api_key,
                timeout=self.timeout_seconds,
                max_retries=0,  # this wrapper controls retries directly
            )
        return self._client


    def _classify_exception(self, exc: Exception) -> str:
        """Classify an anthropic SDK exception into a failure_type string.

        ImportError (e.g. SDK not installed) is an environment problem that cannot
        be resolved by retrying, so it is classified as dependency_missing.
        """
        if isinstance(exc, (ImportError, ModuleNotFoundError)):
            return FAILURE_DEPENDENCY_MISSING

        try:
            import anthropic
        except Exception:
            anthropic = None

        if anthropic is not None:
            timeout_err = getattr(anthropic, "APITimeoutError", None)
            rate_err = getattr(anthropic, "RateLimitError", None)
            internal_err = getattr(anthropic, "InternalServerError", None)
            if timeout_err is not None and isinstance(exc, timeout_err):
                return FAILURE_TIMEOUT
            if rate_err is not None and isinstance(exc, rate_err):
                return FAILURE_RATE_LIMITED
            if internal_err is not None and isinstance(exc, internal_err):
                return FAILURE_SERVER_ERROR

        status_code = getattr(exc, "status_code", None)
        if isinstance(status_code, int):
            if status_code == 429:
                return FAILURE_RATE_LIMITED
            if 500 <= status_code <= 599:
                return FAILURE_SERVER_ERROR

        name = type(exc).__name__.lower()
        if "timeout" in name:
            return FAILURE_TIMEOUT
        if "ratelimit" in name:
            return FAILURE_RATE_LIMITED
        if "server" in name or "internal" in name:
            return FAILURE_SERVER_ERROR

        return FAILURE_SERVER_ERROR

    def _backoff_seconds(self, attempt: int) -> float:
        """Wait time (seconds) before a retry. Always clamped to [1, 30] (Req 7.2)."""
        base = 2 ** attempt
        jitter = random.uniform(0.0, 1.0)
        return min(30.0, max(1.0, base + jitter))

    def _encode_image(self, image_path: str) -> tuple[str, str]:
        """Read an image file and return (base64 string, media_type)."""
        with open(image_path, "rb") as f:
            data = f.read()
        b64 = base64.standard_b64encode(data).decode("ascii")
        media_type, _ = mimetypes.guess_type(image_path)
        if not media_type or not media_type.startswith("image/"):
            media_type = "image/png"
        return b64, media_type

    def _extract_response_text(self, response) -> str:
        """Concatenate the text body from an anthropic messages.create response."""
        parts = []
        content = getattr(response, "content", None) or []
        for block in content:
            text = getattr(block, "text", None)
            if text is None and isinstance(block, dict):
                text = block.get("text")
            if text:
                parts.append(text)
        return "".join(parts)

    def _parse_json(self, text: str) -> Optional[dict]:
        """Parse the response text into a JSON dict. Returns None on failure."""
        if text is None:
            return None
        candidate = text.strip()
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, ValueError):
            pass

        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1 and end > start:
            snippet = candidate[start : end + 1]
            try:
                parsed = json.loads(snippet)
                return parsed if isinstance(parsed, dict) else None
            except (json.JSONDecodeError, ValueError):
                return None
        return None

    def extract(self, image_path: str, prompt: str) -> VisionCallResult:
        """Run a single structured call with image + prompt.

        - If not configured, no network call is made (Req 13.4).
        - 60s timeout (Req 14.6).
        - Retry timeout/429/5xx up to 2 times, waiting 1-30s (Req 7.1, 7.2).
        - Exactly 1 call per image on the happy path (Req 7.5, 14.2).
        - Unparsable response -> failure_type="malformed" (Req 14.5).
        """
        if not self.is_configured():
            logger.warning(
                "Claude credentials missing: image=%s - no request sent",
                image_path,
            )
            return VisionCallResult(
                success=False,
                raw_json=None,
                failure_type=FAILURE_NOT_CONFIGURED,
                error_message="Claude credentials are not configured.",
            )

        try:
            image_b64, media_type = self._encode_image(image_path)
        except (OSError, FileNotFoundError) as exc:
            logger.error("Image read failed: image=%s error=%s", image_path, exc)
            return VisionCallResult(
                success=False,
                raw_json=None,
                failure_type=FAILURE_IMAGE_UNREADABLE,
                error_message=f"Could not read image: {exc}",
            )

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        last_failure_type: Optional[str] = None
        last_error_message: Optional[str] = None

        total_attempts = self.max_retries + 1
        for attempt in range(total_attempts):
            try:
                client = self._get_client()
                response = client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    messages=messages,
                )
            except Exception as exc:
                failure_type = self._classify_exception(exc)
                last_failure_type = failure_type
                last_error_message = str(exc)
                logger.warning(
                    "Claude Vision call failed: type=%s image=%s attempt=%d/%d error=%s",
                    failure_type,
                    image_path,
                    attempt + 1,
                    total_attempts,
                    exc,
                )
                if failure_type not in _RETRYABLE_FAILURES:
                    return VisionCallResult(
                        success=False,
                        raw_json=None,
                        failure_type=failure_type,
                        error_message=last_error_message,
                    )
                if attempt < total_attempts - 1:
                    wait = self._backoff_seconds(attempt)
                    time.sleep(wait)
                    continue
                return VisionCallResult(
                    success=False,
                    raw_json=None,
                    failure_type=failure_type,
                    error_message=last_error_message,
                )

            text = self._extract_response_text(response)
            parsed = self._parse_json(text)
            if parsed is None:
                logger.error(
                    "Claude Vision response parse failed (malformed): image=%s", image_path
                )
                return VisionCallResult(
                    success=False,
                    raw_json=None,
                    failure_type=FAILURE_MALFORMED,
                    error_message="Could not parse response as valid JSON.",
                )

            return VisionCallResult(
                success=True,
                raw_json=parsed,
                failure_type=None,
                error_message=None,
            )

        return VisionCallResult(
            success=False,
            raw_json=None,
            failure_type=last_failure_type or FAILURE_SERVER_ERROR,
            error_message=last_error_message or "unknown error",
        )

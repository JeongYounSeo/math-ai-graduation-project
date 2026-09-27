"""Gemini page-level crop review and detection (one image request per page).

This client only handles the HTTP request and structured response. The crop
service validates every returned box before it may be used for persistence.
"""

import base64
import io
import json
import logging
import time
from pathlib import Path
from typing import Callable, Optional

import httpx
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"
_MAX_INLINE_BYTES = 15 * 1024 * 1024
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["accept_a", "replace", "uncertain"]},
        "reason": {"type": "string"},
        "boxes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "number": {"type": "integer"},
                    "box_2d": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                },
                "required": ["number", "box_2d"],
            },
        },
    },
    "required": ["verdict", "reason", "boxes"],
}


class GeminiCropError(RuntimeError):
    """The page could not be reviewed reliably."""


class GeminiPageCropClient:
    def __init__(
        self,
        api_key: Optional[str],
        model: str = "gemini-3.1-flash-lite",
        *,
        post: Optional[Callable] = None,
    ):
        self.api_key = api_key
        self.model = model
        self._post = post or httpx.post

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def inspect(self, page_image_path: Path, a_boxes: list[dict]) -> dict:
        """Return Gemini's verdict and normalized replacement boxes, if any.

        ``a_boxes`` contains pixel ``crop_box`` values plus optional number.
        Red outlines in the sent image let Gemini check the exact A cut lines.
        """
        if not self.is_configured():
            raise GeminiCropError("GEMINI_API_KEY is not configured")

        image_bytes = self._annotated_page(page_image_path, a_boxes)
        if len(image_bytes) > _MAX_INLINE_BYTES:
            raise GeminiCropError("page image exceeds inline request limit")

        prompt = (
            "This is one page of a Korean math exam or textbook. Each red rectangle is a proposed "
            "complete-problem crop from whitespace analysis. Check the IMAGE, including every "
            "question, formula, diagram and answer choice. Accept A only when all "
            "problems on the page are fully inside separate rectangles and no problem "
            "is missing. If A is absent or any rectangle is wrong, return replacement "
            "boxes for ALL complete problems on this page, not just the bad ones. "
            "Exclude page headings, explanations, notes, page numbers and copyright notices. "
            "If the page contains no complete problems, return replace with an empty boxes array. Use box_2d "
            "as [ymin, xmin, ymax, xmax], integers normalized to 0..1000. "
            "Set number to the visible problem number, or 0 if unreadable. "
            "Use verdict accept_a, replace, or uncertain. Do not solve or transcribe. "
            f"Method A proposed {len(a_boxes)} boxes."
        )
        body = {
            "model": self.model,
            "input": [
                {"type": "text", "text": prompt},
                {
                    "type": "image",
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                    "mime_type": "image/png",
                },
            ],
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": _RESPONSE_SCHEMA,
            },
        }

        for attempt in range(2):
            try:
                response = self._post(
                    _ENDPOINT,
                    headers={"x-goog-api-key": self.api_key},
                    json=body,
                    timeout=60.0,
                )
            except httpx.RequestError as exc:
                if attempt == 0:
                    time.sleep(1)
                    continue
                raise GeminiCropError(f"Gemini request failed: {exc}") from exc

            if response.status_code in {429, 500, 502, 503, 504} and attempt == 0:
                time.sleep(1)
                continue
            if response.status_code != 200:
                raise GeminiCropError(f"Gemini returned HTTP {response.status_code}")
            try:
                interaction = response.json()
                if interaction.get("status") != "completed":
                    raise ValueError("interaction was not completed")
                outputs = [
                    part.get("text", "")
                    for step in interaction.get("steps", [])
                    if step.get("type") == "model_output"
                    for part in step.get("content", [])
                    if part.get("type") == "text"
                ]
                result = json.loads("".join(outputs))
                if not isinstance(result, dict):
                    raise ValueError("structured output is not an object")
                result["_usage"] = interaction.get("usage", {})
                return result
            except (ValueError, TypeError, AttributeError, KeyError) as exc:
                raise GeminiCropError(f"invalid Gemini crop response: {exc}") from exc

        raise GeminiCropError("Gemini request exhausted retries")

    @staticmethod
    def _annotated_page(page_image_path: Path, a_boxes: list[dict]) -> bytes:
        with Image.open(page_image_path) as original:
            image = original.convert("RGB")
        draw = ImageDraw.Draw(image)
        for index, item in enumerate(a_boxes, start=1):
            box = item["crop_box"]
            x, y = int(box["x"]), int(box["y"])
            x2, y2 = x + int(box["width"]), y + int(box["height"])
            draw.rectangle((x, y, x2, y2), outline=(220, 0, 0), width=4)
            label = str(item.get("problem_number") or index)
            draw.text((x + 5, y + 5), label, fill=(220, 0, 0))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

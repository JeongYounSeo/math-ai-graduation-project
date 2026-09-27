import os
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import cv2
from PIL import Image

from app.services.problem_block_grouping_service import process_column, trim_whitespace_from_crop
from app.services.gemini_page_crop_client import GeminiPageCropClient
from app.utils.image_utils import draw_boxes_overlay, get_debug_output_path, save_debug_overlay

# 한 페이지에서 grouping 결과가 이 개수를 넘으면 여전히 너무 잘게 쪼개진 것으로
# 보고 경고 로그를 남긴다 (그래도 저장은 하되, 너무 작은 후보는 이미 grouping
# 단계에서 걸러진 상태다).
MAX_EXPECTED_PROBLEMS_PER_PAGE = 12
logger = logging.getLogger(__name__)


@dataclass
class ProblemCropCandidate:
    page_number: int
    problem_number: Optional[int]
    elective_subject: str
    crop_box: dict
    image_path: str
    crop_method: str = "heuristic"


@dataclass
class PageCropResult:
    candidates: list[ProblemCropCandidate]
    method: str
    needs_review: bool = False
    reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


def infer_elective_subject(page_number: int, layout_config: Optional[dict] = None) -> str:
    config = layout_config or {
        1: "common",
        2: "common",
        3: "common",
        4: "common",
        5: "common",
        6: "common",
        7: "common",
        8: "common",
        9: "probability_statistics",
        10: "probability_statistics",
        11: "probability_statistics",
        12: "probability_statistics",
        13: "calculus",
        14: "calculus",
        15: "calculus",
        16: "calculus",
        17: "geometry",
        18: "geometry",
        19: "geometry",
        20: "geometry",
    }
    return config.get(page_number, "unknown")


# 렌더링 zoom. page_render_service.render_pdf_pages 의 zoom=2.0 과 반드시 일치해야
# 한다(번호 감지는 PDF 원본 좌표, crop_box 는 렌더 이미지 좌표라 이 배율로 변환).
RENDER_ZOOM = 2.0


def _crop_by_problem_numbers(
    page_image_path: Path,
    page_number: int,
    width: int,
    height: int,
    page: Optional[Any],
    zoom: float = RENDER_ZOOM,
    layout_config: Optional[dict] = None,
) -> Optional[list[ProblemCropCandidate]]:
    """감지된 문제 번호의 y좌표(x zoom)를 세로 경계로 삼아 컬럼별로 crop 한다.

    - PDF 원본 좌표의 번호 y 를 zoom 배해 렌더 이미지 좌표(crop_box 좌표계)로 변환.
    - 컬럼(left/right)별로 번호를 y 오름차순 정렬해, 번호 i ~ 번호 i+1 직전을 한 문제로.
      마지막 번호는 페이지 하단(height)까지.
    - 번호가 2개 미만이면 None 을 반환해 기존 밀도/폴백 경로로 넘긴다(번호 없는 자료 하위호환).
    - page 가 없으면(PyMuPDF 폴백) None.
    """
    if page is None:
        return None
    try:
        from app.utils.problem_number_detector import (
            detect_problem_numbers_from_pdf_page,
        )

        nums = detect_problem_numbers_from_pdf_page(page, page_number)
    except Exception:
        return None

    if not nums or len(nums) < 2:
        return None

    subject = infer_elective_subject(page_number, layout_config)
    half = width // 2
    candidates: list[ProblemCropCandidate] = []

    # 여백 trim 용 binary(잉크=nonzero). _crop_by_content_density 와 동일 방식.
    binary = None
    try:
        _img = cv2.imread(str(page_image_path), cv2.IMREAD_COLOR)
        if _img is not None:
            _gray = cv2.cvtColor(_img, cv2.COLOR_BGR2GRAY)
            _blur = cv2.GaussianBlur(_gray, (3, 3), 0)
            _, binary = cv2.threshold(_blur, 245, 255, cv2.THRESH_BINARY_INV)
    except Exception:
        binary = None

    for column in ("left", "right"):
        col_nums = sorted(
            (n for n in nums if n.column == column), key=lambda n: n.y
        )
        x_start = 0 if column == "left" else half
        x_end = half if column == "left" else width
        for i, n in enumerate(col_nums):
            y_start = int(n.y * zoom)
            if i + 1 < len(col_nums):
                y_end = int(col_nums[i + 1].y * zoom)
            else:
                y_end = height
            if y_end - y_start < 1 or x_end - x_start < 1:
                continue
            raw_box = {
                "x": x_start,
                "y": y_start,
                "width": x_end - x_start,
                "height": y_end - y_start,
            }
            # 번호로 나눈 구간은 문제 사이 빈 여백까지 포함하므로, 실제 잉크(글자/
            # 수식/그림) 영역으로 세로를 다시 조인다. trim 실패(잉크 없음 등) 시 원본 유지.
            box = raw_box
            if binary is not None:
                try:
                    trimmed = trim_whitespace_from_crop(binary, raw_box, height)
                    if trimmed:
                        box = trimmed
                except Exception:
                    box = raw_box
            candidates.append(
                ProblemCropCandidate(
                    page_number=page_number,
                    problem_number=n.problem_number,
                    elective_subject=subject,
                    crop_box=box,
                    image_path=str(page_image_path),
                    crop_method="number",
                )
            )

    if len(candidates) < 2:
        return None
    # 읽기 순서(위->아래, 왼->오른쪽)로 정렬.
    candidates.sort(key=lambda c: (c.crop_box["y"], c.crop_box["x"]))
    return candidates


def crop_page_with_gemini(
    page_image_path: Path,
    page_number: int,
    page: Optional[Any],
    vision_client: GeminiPageCropClient,
    layout_config: Optional[dict] = None,
) -> PageCropResult:
    """Review A on the page image, or find every problem with Gemini (B)."""
    with Image.open(page_image_path) as image:
        width, height = image.size
    a_candidates = _crop_by_problem_numbers(
        page_image_path, page_number, width, height, page,
        layout_config=layout_config,
    ) or []
    a_boxes = [
        {"problem_number": item.problem_number, "crop_box": item.crop_box}
        for item in a_candidates
    ]

    def unverified(reason: str, input_tokens: int = 0, output_tokens: int = 0) -> PageCropResult:
        if a_candidates:
            return PageCropResult(a_candidates, "number_unverified", True, reason, input_tokens, output_tokens)
        fallback = _crop_by_content_density(
            page_image_path, page_number, width, height, layout_config
        ) or _crop_fallback(page_image_path, page_number, width, height, layout_config)
        return PageCropResult(fallback, "heuristic_unverified", True, reason, input_tokens, output_tokens)

    try:
        decision = vision_client.inspect(page_image_path, a_boxes)
    except Exception as exc:
        logger.warning("Gemini crop review failed on page %s: %s", page_number, exc)
        return unverified(str(exc))

    usage = decision.get("_usage", {})
    input_tokens = usage.get("total_input_tokens", 0) if isinstance(usage, dict) else 0
    output_tokens = usage.get("total_output_tokens", 0) if isinstance(usage, dict) else 0
    if decision.get("verdict") == "accept_a" and a_candidates:
        return PageCropResult(a_candidates, "number_verified", False, decision.get("reason", ""), input_tokens, output_tokens)
    if decision.get("verdict") == "replace":
        try:
            replacements = _candidates_from_gemini_boxes(
                decision.get("boxes"), page_image_path, page_number,
                width, height, layout_config,
            )
        except ValueError as exc:
            logger.warning("Gemini crop boxes rejected on page %s: %s", page_number, exc)
            return unverified(str(exc), input_tokens, output_tokens)
        return PageCropResult(replacements, "gemini", False, decision.get("reason", ""), input_tokens, output_tokens)
    return unverified(
        f"Gemini verdict: {decision.get('verdict', 'invalid')}", input_tokens, output_tokens
    )


def _candidates_from_gemini_boxes(
    raw_boxes: object,
    page_image_path: Path,
    page_number: int,
    width: int,
    height: int,
    layout_config: Optional[dict],
) -> list[ProblemCropCandidate]:
    """Validate all normalized boxes before accepting any Gemini crop."""
    if not isinstance(raw_boxes, list) or not 1 <= len(raw_boxes) <= MAX_EXPECTED_PROBLEMS_PER_PAGE:
        raise ValueError("invalid problem count")
    seen_numbers: set[int] = set()
    candidates: list[ProblemCropCandidate] = []
    for item in raw_boxes:
        if not isinstance(item, dict):
            raise ValueError("box item is not an object")
        coords = item.get("box_2d")
        number = item.get("number")
        if not isinstance(coords, list) or len(coords) != 4 or any(
            isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 1000
            for v in coords
        ):
            raise ValueError("box_2d must have four 0..1000 integers")
        if isinstance(number, bool) or not isinstance(number, int) or not 0 <= number <= 30:
            raise ValueError("invalid problem number")
        if number and number in seen_numbers:
            raise ValueError("duplicate problem number")
        if number:
            seen_numbers.add(number)
        ymin, xmin, ymax, xmax = coords
        if ymin >= ymax or xmin >= xmax:
            raise ValueError("inverted or empty box")
        x1, x2 = round(xmin * width / 1000), round(xmax * width / 1000)
        y1, y2 = round(ymin * height / 1000), round(ymax * height / 1000)
        if x2 - x1 < max(40, width * 0.10) or y2 - y1 < max(40, height * 0.025):
            raise ValueError("problem box is too small")
        candidates.append(
            ProblemCropCandidate(
                page_number=page_number,
                problem_number=number or None,
                elective_subject=infer_elective_subject(page_number, layout_config),
                crop_box={"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1},
                image_path=str(page_image_path),
                crop_method="gemini",
            )
        )
    for index, first in enumerate(candidates):
        a = first.crop_box
        for second in candidates[index + 1:]:
            b = second.crop_box
            overlap_w = max(0, min(a["x"] + a["width"], b["x"] + b["width"]) - max(a["x"], b["x"]))
            overlap_h = max(0, min(a["y"] + a["height"], b["y"] + b["height"]) - max(a["y"], b["y"]))
            intersection = overlap_w * overlap_h
            if intersection / min(a["width"] * a["height"], b["width"] * b["height"]) > 0.15:
                raise ValueError("problem boxes overlap heavily")
    candidates.sort(key=lambda c: (c.crop_box["y"], c.crop_box["x"]))
    return candidates


def crop_problem_candidates(
    page_image_path: Path,
    page_number: int,
    page: Optional[Any] = None,
    layout_config: Optional[dict] = None,
) -> list[ProblemCropCandidate]:
    """이미지 레이아웃을 분석해 문제 후보 영역을 분할한다."""
    image = Image.open(page_image_path)
    width, height = image.size
    candidates: list[ProblemCropCandidate] = []

    if width <= 0 or height <= 0:
        return candidates

    # ---- 번호 기반 분할 우선(2026-09-25): 문제 번호가 텍스트로 읽히면 그 y좌표를
    #      경계로 정확히 자른다. 번호 <2개(스캔본/논술)면 None -> 기존 밀도/폴백. ----
    number_based = _crop_by_problem_numbers(
        page_image_path, page_number, width, height, page, layout_config=layout_config
    )
    if number_based:
        return number_based

    candidates = _crop_by_content_density(
        page_image_path,
        page_number,
        width,
        height,
        layout_config,
    )

    if candidates:
        return candidates

    return _crop_fallback(page_image_path, page_number, width, height, layout_config)


def _crop_by_content_density(
    page_image_path: Path,
    page_number: int,
    page_width: int,
    page_height: int,
    layout_config: Optional[dict],
) -> list[ProblemCropCandidate]:
    """OpenCV로 찾은 작은 content block들을 '문제 단위' group으로 병합해 분할한다.

    작은 block(글자 한 줄, 수식, 섹션 라벨 등)을 바로 Problem 후보로 저장하지
    않고, app.services.problem_block_grouping_service를 통해 먼저 병합한 뒤
    최종 문제 후보(group)만 반환한다.
    """
    image = cv2.imread(str(page_image_path), cv2.IMREAD_COLOR)
    if image is None:
        return []

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, binary = cv2.threshold(blur, 245, 255, cv2.THRESH_BINARY_INV)

    left_margin_ratio = 0.49
    right_margin_ratio = 0.51

    debug_enabled = os.getenv("DEBUG_CROP", "").lower() in {"1", "true", "yes"}

    candidates: list[ProblemCropCandidate] = []
    debug_blocks: list[dict] = []
    debug_before_boxes: list[dict] = []
    debug_after_boxes: list[dict] = []

    columns = (
        ("left", 0, int(page_width * left_margin_ratio)),
        ("right", int(page_width * right_margin_ratio), page_width),
    )

    for column_name, x_start, x_end in columns:
        if x_end <= x_start:
            continue

        result = process_column(binary, column_name, x_start, x_end, page_width, page_height)

        print(
            f"[crop] page={page_number} column={column_name} "
            f"raw_blocks={len(result.raw_blocks)} grouped_problems={len(result.crop_boxes)}"
        )

        if debug_enabled:
            debug_blocks.extend(block.to_dict() for block in result.filtered_blocks)

        for index, group_result in enumerate(result.group_results, start=1):
            group_label = f"{column_name}-{index}"
            before = group_result.before_box
            after = group_result.after_box

            if debug_enabled:
                debug_before_boxes.append(_to_corner_box(before))
                if group_result.kept and after is not None:
                    debug_after_boxes.append(_to_corner_box(after))

            if not group_result.kept or after is None:
                print(
                    f"[crop-trim] page={page_number} group={group_label} "
                    f"before={_box_tuple(before)} skipped ({group_result.reason})"
                )
                continue

            print(
                f"[crop-trim] page={page_number} group={group_label} "
                f"before={_box_tuple(before)} after={_box_tuple(after)}"
            )

            candidate = ProblemCropCandidate(
                page_number=page_number,
                problem_number=None,
                elective_subject=infer_elective_subject(page_number, layout_config),
                crop_box=after,
                image_path=str(page_image_path),
            )
            candidates.append(candidate)

    if len(candidates) > MAX_EXPECTED_PROBLEMS_PER_PAGE:
        print(
            f"[crop] page={page_number} warning: grouped_problems={len(candidates)} "
            f"exceeds expected max ({MAX_EXPECTED_PROBLEMS_PER_PAGE}); keeping all "
            "validated groups since small candidates were already filtered out."
        )

    if debug_enabled:
        blocks_image = draw_boxes_overlay(image, debug_blocks, color=(255, 0, 0), label_prefix="b")
        groups_image = draw_boxes_overlay(image, debug_before_boxes, color=(0, 0, 255), label_prefix="g")
        groups_image = draw_boxes_overlay(groups_image, debug_after_boxes, color=(0, 200, 0), label_prefix="f")
        save_debug_overlay(blocks_image, get_debug_output_path(page_image_path, page_number, "blocks"))
        save_debug_overlay(groups_image, get_debug_output_path(page_image_path, page_number, "groups"))

    print(f"[crop] page={page_number} total_candidates={len(candidates)}")
    return candidates


def _to_corner_box(box: dict) -> dict:
    """{x, y, width, height} 형태를 draw_boxes_overlay가 기대하는
    {x1, y1, x2, y2} 형태로 변환한다."""
    return {
        "x1": box["x"],
        "y1": box["y"],
        "x2": box["x"] + box["width"],
        "y2": box["y"] + box["height"],
    }


def _box_tuple(box: dict) -> tuple:
    return (box["x"], box["y"], box["x"] + box["width"], box["y"] + box["height"])


def _crop_fallback(
    page_image_path: Path,
    page_number: int,
    page_width: int,
    page_height: int,
    layout_config: Optional[dict],
) -> list[ProblemCropCandidate]:
    """
    기본 heuristic crop: 2단 또는 3단 레이아웃
    """
    candidates: list[ProblemCropCandidate] = []

    # 기본 2단 레이아웃
    left_box = {"x": 0, "y": 80, "width": page_width // 2 - 10, "height": page_height - 160}
    right_box = {"x": page_width // 2 + 10, "y": 80, "width": page_width // 2 - 10, "height": page_height - 160}

    for index, box in enumerate([left_box, right_box], start=1):
        candidate = ProblemCropCandidate(
            page_number=page_number,
            problem_number=None,
            elective_subject=infer_elective_subject(page_number, layout_config),
            crop_box=box,
            image_path=str(page_image_path),
        )
        candidates.append(candidate)

    if page_number <= 8:
        # 공통문항은 2개 후보만 만든다.
        return candidates

    # 선택과목 페이지는 2개 또는 3개 후보로 확장
    if page_height > 1200:
        extra_box = {"x": 0, "y": page_height // 2 + 40, "width": page_width, "height": page_height // 2 - 120}
        candidates.append(
            ProblemCropCandidate(
                page_number=page_number,
                problem_number=None,
                elective_subject=infer_elective_subject(page_number, layout_config),
                crop_box=extra_box,
                image_path=str(page_image_path),
            )
        )
    return candidates

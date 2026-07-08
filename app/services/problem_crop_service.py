import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import cv2
from PIL import Image

from app.services.problem_block_grouping_service import process_column
from app.utils.image_utils import draw_boxes_overlay, get_debug_output_path, save_debug_overlay

# 한 페이지에서 grouping 결과가 이 개수를 넘으면 여전히 너무 잘게 쪼개진 것으로
# 보고 경고 로그를 남긴다 (그래도 저장은 하되, 너무 작은 후보는 이미 grouping
# 단계에서 걸러진 상태다).
MAX_EXPECTED_PROBLEMS_PER_PAGE = 12


@dataclass
class ProblemCropCandidate:
    page_number: int
    problem_number: Optional[int]
    elective_subject: str
    crop_box: dict
    image_path: str


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

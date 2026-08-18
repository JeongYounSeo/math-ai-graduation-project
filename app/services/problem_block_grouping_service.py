"""OpenCV content block을 '문제 단위' group으로 병합하는 로직.

기존 crop 파이프라인은 OpenCV로 찾은 작은 content block(글자 한 줄, 수식,
"5지선다형" 라벨 등)을 그대로 Problem 후보로 저장해서 문제 하나가 여러 개의
잘게 쪼개진 후보로 나뉘는 문제가 있었다. 이 모듈은 block을 찾는 단계와,
찾은 block들을 문제 단위로 묶는 grouping 단계를 분리해서 최종적으로는
"문제 하나 = group 하나"가 되도록 만든다.
"""

from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

# 페이지 상단/하단에서 헤더(제목, "5지선다형" 등)와 페이지 번호를 제거하기 위한 비율.
HEADER_ZONE_RATIO = 0.12
FOOTER_ZONE_RATIO = 0.06

# "확인 사항" 같은 시험 안내 박스를 배제하기 위해 살펴보는 하단 영역 비율.
INSTRUCTION_BOX_ZONE_RATIO = 0.70

# raw block 노이즈 제거 기준 (너무 작은 얼룩은 block으로 취급하지 않는다).
MIN_RAW_BLOCK_AREA = 150

# 최종 crop 후보 검증 기준.
MIN_FINAL_HEIGHT = 150
MIN_FINAL_WIDTH = 150
MIN_FINAL_INK_RATIO = 0.0015

PADDING_X = 30
PADDING_Y = 35


def _compute_thresholds(page_height: int) -> tuple[int, int]:
    """grouping에 쓰는 merge_gap_threshold와 min_problem_height를 계산한다."""
    merge_gap_threshold = max(220, int(page_height * 0.07))
    min_problem_height = max(260, int(page_height * 0.10))
    return merge_gap_threshold, min_problem_height


@dataclass
class Block:
    x1: int
    y1: int
    x2: int
    y2: int
    column: str
    area: int
    ink_ratio: float

    def to_dict(self) -> dict:
        return {
            "x1": self.x1,
            "y1": self.y1,
            "x2": self.x2,
            "y2": self.y2,
            "column": self.column,
            "area": self.area,
            "ink_ratio": self.ink_ratio,
        }


@dataclass
class ProblemGroup:
    column: str
    blocks: list = field(default_factory=list)
    crop_box: Optional[dict] = None


def compute_ink_ratio(binary: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> float:
    """binary 이미지(ink=nonzero) 안에서 주어진 영역의 ink 비율을 계산한다."""
    x1c = max(0, int(x1))
    y1c = max(0, int(y1))
    x2c = min(binary.shape[1], int(x2))
    y2c = min(binary.shape[0], int(y2))
    if x2c <= x1c or y2c <= y1c:
        return 0.0
    region = binary[y1c:y2c, x1c:x2c]
    area = region.size
    if area == 0:
        return 0.0
    return float(np.count_nonzero(region)) / float(area)


def _compute_kernel_size(column_width: int, page_height: int) -> tuple[int, int]:
    """글자/수식/도형이 가까이 있으면 같은 block으로 묶이도록 넉넉한 kernel을 만든다."""
    kernel_w = max(25, int(column_width * 0.05))
    kernel_h = max(12, int(page_height * 0.012))
    return kernel_w, kernel_h


def find_content_blocks(
    binary: np.ndarray,
    x_start: int,
    x_end: int,
    page_width: int,
    page_height: int,
    column: str,
) -> list[Block]:
    """column 내부에서 morphology close/dilate를 적용해 작은 content block을 찾는다."""
    if x_end <= x_start:
        return []

    column_binary = binary[:, x_start:x_end]
    kernel_w, kernel_h = _compute_kernel_size(x_end - x_start, page_height)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_w, kernel_h))
    closed = cv2.morphologyEx(column_binary, cv2.MORPH_CLOSE, kernel)
    dilated = cv2.dilate(closed, kernel, iterations=1)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    blocks: list[Block] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w * h < MIN_RAW_BLOCK_AREA:
            continue

        abs_x1 = x_start + x
        abs_x2 = x_start + x + w
        y1, y2 = y, y + h
        ink_ratio = compute_ink_ratio(binary, abs_x1, y1, abs_x2, y2)
        if ink_ratio <= 0:
            continue

        blocks.append(
            Block(
                x1=abs_x1,
                y1=y1,
                x2=abs_x2,
                y2=y2,
                column=column,
                area=int(w * h),
                ink_ratio=ink_ratio,
            )
        )

    blocks.sort(key=lambda b: b.y1)
    return blocks


def filter_header_footer(blocks: list[Block], page_width: int, page_height: int) -> list[Block]:
    """상단 헤더/섹션 라벨과 하단 페이지 번호 block을 제거한다.

    block이 헤더/푸터 영역에 '완전히' 포함될 때만 제거해서, 문제 본문이
    페이지 상단에 바로 시작하는 경우까지 지우지 않도록 한다.
    """
    header_cutoff = int(page_height * HEADER_ZONE_RATIO)
    footer_cutoff = int(page_height * (1 - FOOTER_ZONE_RATIO))

    kept: list[Block] = []
    for block in blocks:
        if block.y2 <= header_cutoff:
            continue
        if block.y1 >= footer_cutoff:
            continue
        kept.append(block)
    return kept


def group_blocks(blocks: list[Block], page_height: int) -> list[list[Block]]:
    """gap 기반으로 block들을 '문제 단위' group으로 병합한다."""
    if not blocks:
        return []

    merge_gap_threshold, min_problem_height = _compute_thresholds(page_height)

    sorted_blocks = sorted(blocks, key=lambda b: b.y1)

    groups: list[list[Block]] = []
    current: list[Block] = []

    for block in sorted_blocks:
        if not current:
            current = [block]
            continue

        current_y1 = min(b.y1 for b in current)
        current_y2 = max(b.y2 for b in current)
        current_height = current_y2 - current_y1
        gap = block.y1 - current_y2

        # gap이 작으면 같은 문제. group이 아직 min_problem_height보다 작으면
        # gap이 크더라도 강제로 병합해서 문제 하나가 잘게 쪼개지지 않게 한다.
        if gap <= merge_gap_threshold or current_height < min_problem_height:
            current.append(block)
        else:
            groups.append(current)
            current = [block]

    if current:
        groups.append(current)

    # 마지막 group이 너무 작으면 이전 group에 흡수시킨다.
    if len(groups) >= 2:
        last = groups[-1]
        last_height = max(b.y2 for b in last) - min(b.y1 for b in last)
        if last_height < min_problem_height:
            groups[-2].extend(groups.pop())

    return groups


def build_group_crop_box(
    group: list[Block],
    column_x_start: int,
    column_x_end: int,
    page_width: int,
    page_height: int,
    padding_x: int = PADDING_X,
    padding_y: int = PADDING_Y,
) -> dict:
    """group의 union bbox에 padding을 더해 최종 crop box를 만든다.

    x축은 block union이 아니라 column 전체 폭을 넉넉히 포함한다 (그래프/보기가
    block 검출 범위보다 오른쪽으로 더 뻗어 있는 경우를 대비). 단, 중앙 세로선
    쪽 padding이 반대 column을 침범하지 않도록 페이지 중앙에서 clamp한다.
    """
    y1 = min(b.y1 for b in group)
    y2 = max(b.y2 for b in group)

    page_mid = page_width / 2
    x1 = max(0, column_x_start - padding_x)
    x2 = min(page_width, column_x_end + padding_x)
    if column_x_start >= page_mid:
        # right column: 왼쪽(안쪽) 경계가 중앙선을 넘지 않게 한다.
        x1 = max(x1, int(page_mid))
    else:
        # left column: 오른쪽(안쪽) 경계가 중앙선을 넘지 않게 한다.
        x2 = min(x2, int(page_mid))
    y1p = max(0, y1 - padding_y)
    y2p = min(page_height, y2 + padding_y)

    return {
        "x": int(x1),
        "y": int(y1p),
        "width": max(1, int(x2 - x1)),
        "height": max(1, int(y2p - y1p)),
    }


def is_valid_final_crop(binary: np.ndarray, crop_box: dict) -> bool:
    """비어있거나 너무 작은 최종 후보를 걸러낸다."""
    if crop_box["height"] < MIN_FINAL_HEIGHT:
        return False
    if crop_box["width"] < MIN_FINAL_WIDTH:
        return False

    x1, y1 = crop_box["x"], crop_box["y"]
    x2, y2 = x1 + crop_box["width"], y1 + crop_box["height"]
    ink_ratio = compute_ink_ratio(binary, x1, y1, x2, y2)
    if ink_ratio < MIN_FINAL_INK_RATIO:
        return False

    return True


def trim_whitespace_from_crop(
    binary: np.ndarray,
    crop_box: dict,
    page_height: int,
    padding_x: int = PADDING_X,
    padding_y: int = PADDING_Y,
) -> Optional[dict]:
    """crop_box 내부에서 실제 글자/수식/그림(ink)이 있는 영역을 다시 찾고,
    상하 빈 여백을 제거한 crop_box를 반환한다.

    - 세로(y)는 실제 ink pixel의 min_y/max_y 기준으로 타이트하게 잡되 padding_y를 유지한다.
    - 가로(x)는 column 전체 폭을 그대로 유지한다 (수식/그래프가 오른쪽으로 길게
      이어질 수 있으므로 너무 타이트하게 자르지 않는다).
    - 페이지 상단 header 영역과 하단 footer 영역은 ink 탐색 대상에서 제외해서,
      강제 병합으로 섞여 들어간 헤더/페이지번호가 최종 crop에 포함되지 않게 한다.
    - group_blocks의 min_problem_height 강제 병합 때문에 merge_gap_threshold보다
      큰 내부 gap 너머의 이질적인 content(예: 확인 사항 안내 박스)가 같은 group에
      섞여 들어간 경우, 첫 번째 content cluster까지만 남기고 나머지는 잘라낸다.
    - header/footer 영역 안에만 ink가 있는 경우(유효한 문제 내용이 없는 경우)는
      None을 반환한다.
    """
    page_h, page_w = binary.shape[:2]
    x1 = max(0, int(crop_box["x"]))
    y1 = max(0, int(crop_box["y"]))
    x2 = min(page_w, x1 + int(crop_box["width"]))
    y2 = min(page_h, y1 + int(crop_box["height"]))
    if x2 <= x1 or y2 <= y1:
        return None

    header_cutoff = int(page_height * HEADER_ZONE_RATIO)
    footer_cutoff = int(page_height * (1 - FOOTER_ZONE_RATIO))

    search_y1 = max(y1, header_cutoff)
    search_y2 = min(y2, footer_cutoff)
    if search_y2 <= search_y1:
        return None

    region = binary[search_y1:search_y2, x1:x2]
    ink_rows = np.where(np.any(region > 0, axis=1))[0]
    if ink_rows.size == 0:
        return None

    merge_gap_threshold, _ = _compute_thresholds(page_height)
    cluster_end = 0
    for i in range(1, ink_rows.size):
        row_gap = int(ink_rows[i]) - int(ink_rows[i - 1]) - 1
        if row_gap > merge_gap_threshold:
            break
        cluster_end = i
    first_cluster_rows = ink_rows[: cluster_end + 1]

    ink_y1 = search_y1 + int(first_cluster_rows[0])
    ink_y2 = search_y1 + int(first_cluster_rows[-1]) + 1

    trimmed_y1 = max(header_cutoff, ink_y1 - padding_y)
    trimmed_y2 = min(footer_cutoff, ink_y2 + padding_y)

    return {
        "x": x1,
        "y": int(trimmed_y1),
        "width": max(1, x2 - x1),
        "height": max(1, int(trimmed_y2 - trimmed_y1)),
    }


def is_instruction_box_crop(crop_box: dict, page_height: int, min_problem_height: int) -> bool:
    """"확인 사항"처럼 시험 안내 영역으로 보이는 후보인지 위치/크기 기반으로 판단한다.

    OCR을 사용하지 않으므로 문제 번호 유무를 직접 읽을 수는 없다. 대신,
    - 페이지 하단(INSTRUCTION_BOX_ZONE_RATIO 이후)에서 시작하고,
    - 실제 content 기준 height가 min_problem_height보다 작으면
    문제 본문이라기엔 세로로 짧은 안내 박스로 보고 제외한다.
    """
    bottom_zone_start = int(page_height * INSTRUCTION_BOX_ZONE_RATIO)
    if crop_box["y"] < bottom_zone_start:
        return False
    return crop_box["height"] < min_problem_height


@dataclass
class GroupCropResult:
    column: str
    before_box: dict
    after_box: Optional[dict]
    kept: bool
    reason: Optional[str] = None


@dataclass
class ColumnGroupingResult:
    column: str
    raw_blocks: list
    filtered_blocks: list
    groups: list  # list[list[Block]], grouping 단계를 통과한 group만 (trim 전)
    group_results: list  # list[GroupCropResult], trim 전/후 정보를 포함한 전체 시도 기록
    crop_boxes: list  # list[dict], 최종 저장 대상 crop box만 (trim 후)


def process_column(
    binary: np.ndarray,
    column: str,
    x_start: int,
    x_end: int,
    page_width: int,
    page_height: int,
) -> ColumnGroupingResult:
    """column 하나에 대해 block 검출 -> header/footer 제거 -> grouping ->
    (trim 전) crop box 생성 -> whitespace trim -> 최종 검증까지 수행한다.
    """
    raw_blocks = find_content_blocks(binary, x_start, x_end, page_width, page_height, column)
    filtered_blocks = filter_header_footer(raw_blocks, page_width, page_height)
    groups = group_blocks(filtered_blocks, page_height)
    _, min_problem_height = _compute_thresholds(page_height)

    group_results: list[GroupCropResult] = []
    crop_boxes: list[dict] = []

    for group in groups:
        before_box = build_group_crop_box(group, x_start, x_end, page_width, page_height)

        after_box = trim_whitespace_from_crop(binary, before_box, page_height)
        if after_box is None:
            group_results.append(GroupCropResult(column, before_box, None, False, "empty_after_trim"))
            continue

        if not is_valid_final_crop(binary, after_box):
            group_results.append(GroupCropResult(column, before_box, after_box, False, "too_small_or_empty"))
            continue

        if is_instruction_box_crop(after_box, page_height, min_problem_height):
            group_results.append(GroupCropResult(column, before_box, after_box, False, "instruction_box"))
            continue

        group_results.append(GroupCropResult(column, before_box, after_box, True, None))
        crop_boxes.append(after_box)

    return ColumnGroupingResult(
        column=column,
        raw_blocks=raw_blocks,
        filtered_blocks=filtered_blocks,
        groups=groups,
        group_results=group_results,
        crop_boxes=crop_boxes,
    )

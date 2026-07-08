import numpy as np

from app.services.problem_block_grouping_service import (
    Block,
    filter_header_footer,
    group_blocks,
    process_column,
)


def test_body_and_choices_blocks_merge_into_one_group():
    """본문 block과 보기(answer choices) block은 gap이 작으면 하나의 문제 group으로 병합돼야 한다."""
    page_height = 1600
    body = Block(x1=100, y1=300, x2=500, y2=500, column="left", area=80000, ink_ratio=0.1)
    choices = Block(x1=100, y1=520, x2=500, y2=600, column="left", area=32000, ink_ratio=0.1)

    groups = group_blocks([body, choices], page_height)

    assert len(groups) == 1
    assert body in groups[0]
    assert choices in groups[0]


def test_small_first_block_forces_merge_with_next_despite_large_gap():
    """group height가 min_problem_height보다 작으면 gap이 크더라도 다음 block과 강제 병합돼야 한다."""
    page_height = 1600
    small_block = Block(x1=100, y1=300, x2=500, y2=340, column="left", area=1, ink_ratio=0.1)
    next_block = Block(x1=100, y1=700, x2=500, y2=900, column="left", area=1, ink_ratio=0.1)

    groups = group_blocks([small_block, next_block], page_height)

    assert len(groups) == 1
    assert small_block in groups[0]
    assert next_block in groups[0]


def test_header_block_is_removed():
    """페이지 상단 header zone에 완전히 포함된 block(제목, "5지선다형" 등)은 제거된다."""
    page_height = 1600
    page_width = 1200
    header = Block(x1=100, y1=20, x2=900, y2=150, column="left", area=1, ink_ratio=0.1)
    section_label = Block(x1=100, y1=30, x2=260, y2=70, column="left", area=1, ink_ratio=0.1)
    body = Block(x1=100, y1=300, x2=500, y2=700, column="left", area=1, ink_ratio=0.1)

    kept = filter_header_footer([header, section_label, body], page_width, page_height)

    assert header not in kept
    assert section_label not in kept
    assert body in kept


def test_body_starting_near_top_is_not_removed():
    """문제 본문이 header zone에서 시작해 아래까지 길게 이어지면 제거하지 않는다."""
    page_height = 1600
    page_width = 1200
    body_near_top = Block(x1=100, y1=100, x2=900, y2=700, column="left", area=1, ink_ratio=0.1)

    kept = filter_header_footer([body_near_top], page_width, page_height)

    assert body_near_top in kept


def test_footer_block_is_removed():
    """페이지 하단 footer zone에 완전히 포함된 block(페이지 번호)은 제거된다."""
    page_height = 1600
    page_width = 1200
    footer = Block(x1=550, y1=1550, x2=650, y2=1580, column="left", area=1, ink_ratio=0.1)
    body = Block(x1=100, y1=300, x2=500, y2=700, column="left", area=1, ink_ratio=0.1)

    kept = filter_header_footer([footer, body], page_width, page_height)

    assert footer not in kept
    assert body in kept


def test_two_column_page_groups_are_not_over_split():
    """2단 페이지에서 촘촘한 줄 간격 때문에 최종 group이 잘게 쪼개지지 않아야 한다."""
    page_width = 1200
    page_height = 1600
    binary = np.zeros((page_height, page_width), dtype=np.uint8)

    # 왼쪽 column: 본문 세 줄 + 보기 두 줄로 구성된 문제 하나
    left_lines = [
        (60, 300, 500, 330),
        (60, 345, 480, 375),
        (60, 390, 520, 420),
        (60, 460, 500, 490),
        (60, 505, 500, 535),
    ]
    for x1, y1, x2, y2 in left_lines:
        binary[y1:y2, x1:x2] = 255

    # 오른쪽 column: 별도 문제 하나 (본문 세 줄)
    right_lines = [
        (650, 320, 1100, 350),
        (650, 365, 1080, 395),
        (650, 410, 1100, 440),
    ]
    for x1, y1, x2, y2 in right_lines:
        binary[y1:y2, x1:x2] = 255

    left_result = process_column(binary, "left", 0, int(page_width * 0.49), page_width, page_height)
    right_result = process_column(binary, "right", int(page_width * 0.51), page_width, page_width, page_height)

    assert len(left_result.crop_boxes) == 1
    assert len(right_result.crop_boxes) == 1

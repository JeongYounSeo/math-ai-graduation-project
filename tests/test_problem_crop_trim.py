import numpy as np

from app.services.problem_block_grouping_service import (
    is_instruction_box_crop,
    process_column,
    trim_whitespace_from_crop,
)


def test_large_empty_vertical_margin_is_trimmed_to_content():
    """group box 안에 빈 여백이 많으면, 실제 ink가 있는 영역 기준으로 크게 줄어들어야 한다."""
    page_height = 1600
    page_width = 1200
    binary = np.zeros((page_height, page_width), dtype=np.uint8)
    binary[700:760, 100:500] = 255  # 실제 내용은 60px 높이 뿐

    oversized_before_box = {"x": 0, "y": 150, "width": 830, "height": 1300}

    after = trim_whitespace_from_crop(binary, oversized_before_box, page_height)

    assert after is not None
    assert after["height"] < oversized_before_box["height"]
    # ink(60px) + padding_y*2(70px) 근처로 줄어들어야 한다.
    assert after["height"] < 300


def test_footer_page_number_is_excluded_from_final_crop():
    """crop box 안에 footer 영역의 페이지 번호가 섞여 있어도 최종 crop에는 포함되지 않아야 한다."""
    page_height = 1600
    page_width = 1200
    binary = np.zeros((page_height, page_width), dtype=np.uint8)
    binary[700:900, 100:500] = 255  # 문제 본문
    binary[1550:1580, 550:650] = 255  # 하단 페이지 번호 (footer zone)

    before_box = {"x": 0, "y": 150, "width": 830, "height": 1440}
    footer_cutoff = int(page_height * (1 - 0.06))

    after = trim_whitespace_from_crop(binary, before_box, page_height)

    assert after is not None
    assert after["y"] + after["height"] <= footer_cutoff


def test_min_problem_height_does_not_force_final_crop_to_grow():
    """min_problem_height는 grouping 단계에서만 쓰이고, 최종 crop height를 강제로 늘리지 않는다."""
    page_height = 1600
    page_width = 1200
    binary = np.zeros((page_height, page_width), dtype=np.uint8)
    binary[700:740, 100:500] = 255  # 실제 내용은 40px 높이 뿐인 짧은 문제

    before_box = {"x": 0, "y": 650, "width": 830, "height": 150}

    after = trim_whitespace_from_crop(binary, before_box, page_height)

    min_problem_height = max(260, int(page_height * 0.10))
    assert after is not None
    assert after["height"] < min_problem_height


def test_instruction_box_like_candidate_is_not_saved_as_problem():
    """하단 30% 영역에 위치하고 세로 길이가 짧은 candidate는 '확인 사항' 안내 박스로 보고 제외한다."""
    page_height = 1600
    min_problem_height = max(260, int(page_height * 0.10))

    instruction_box_crop = {"x": 0, "y": 1250, "width": 830, "height": 200}
    assert instruction_box_crop["height"] < min_problem_height
    assert is_instruction_box_crop(instruction_box_crop, page_height, min_problem_height) is True

    real_problem_crop = {"x": 0, "y": 700, "width": 830, "height": 300}
    assert is_instruction_box_crop(real_problem_crop, page_height, min_problem_height) is False


def test_trim_drops_far_away_content_pulled_in_by_forced_merge():
    """min_problem_height 강제 병합으로 멀리 떨어진 안내 박스가 같은 group에 섞여
    들어가더라도, trim은 첫 번째 content cluster(실제 문제)만 남겨야 한다.
    """
    page_height = 1600
    page_width = 1200
    binary = np.zeros((page_height, page_width), dtype=np.uint8)

    # 문제 본문 + 보기: 둘을 합쳐도 min_problem_height(260)보다 작다.
    binary[300:420, 60:500] = 255
    binary[460:540, 60:500] = 255

    # group_blocks가 min_problem_height 미달로 강제 병합해 끌고 온, 멀리 떨어진
    # 확인 사항 안내 박스.
    binary[1250:1380, 60:500] = 255

    # 강제 병합 이후 그룹 전체를 감싸는 (부풀려진) group box.
    oversized_group_box = {"x": 0, "y": 254, "width": 600, "height": 1173}

    after = trim_whitespace_from_crop(binary, oversized_group_box, page_height)

    assert after is not None
    # 안내 박스(1250~1380)가 포함되지 않도록, trim된 영역은 문제 본문+보기 근처에서 끝나야 한다.
    assert after["y"] + after["height"] < 1000


def test_process_column_drops_instruction_box_group_but_keeps_real_problem():
    """실제 문제 group은 유지하면서, 하단의 짧은 안내 박스성 group은 최종 crop_boxes에서 빠져야 한다."""
    page_width = 1200
    page_height = 1600
    binary = np.zeros((page_height, page_width), dtype=np.uint8)

    # 실제 문제: 넉넉한 높이 (600px)
    binary[300:900, 60:500] = 255

    # 확인 사항 같은 안내 박스: 하단 30% 영역, 세로로는 짧음 (130px)
    binary[1250:1380, 60:500] = 255

    result = process_column(binary, "left", 0, int(page_width * 0.49), page_width, page_height)

    assert len(result.crop_boxes) == 1
    kept_box = result.crop_boxes[0]
    # 실제 문제 영역과 겹치고, 안내 박스 영역(1250~1380)은 최종 결과에 없어야 한다.
    assert kept_box["y"] < 1000

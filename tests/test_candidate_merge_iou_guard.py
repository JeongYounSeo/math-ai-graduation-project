"""merge 단계 IoU 가드 회귀/신규 테스트 (정본 설계 §7 / DESIGN_region_coord_validation §4.2).

`_merge_boxes` 는 union **전에** 관계(CONTAINED/HEAVY/DISJOINT/TOUCHING)를 판정해
과병합(HEAVY)을 방지하고 포함(CONTAINED)은 흡수한다.

이 단계는 파이프라인의 ENABLE_REGION_OVERLAP_VALIDATION 플래그와 무관하며
merge 가드는 항상 동작한다(region 검증기 파이프라인 훅 연결은 5단계).
"""

from pathlib import Path

from PIL import Image

from app.services.problem_candidate_merge_service import (
    _merge_boxes,
    _merge_boxes_guarded,
    merge_classified_candidates,
)
from app.services.problem_crop_service import ProblemCropCandidate


def _create_page_image(path: Path) -> Path:
    image = Image.new("RGB", (800, 1000), "white")
    image.save(path)
    return path


def _classification(*, save: bool, merge: bool, number=None) -> dict:
    return {
        "candidate_type": "problem" if not merge else "answer_choices",
        "is_problem_related": True,
        "problem_number": number,
        "score": None,
        "should_save_as_problem": save,
        "should_merge_with_previous": merge,
        "confidence": 0.9,
        "reason": "test",
    }


def test_disjoint_answer_choices_merge_into_previous_snapshot(tmp_path):
    """DISJOINT 관계: 세로로 겹치지 않는 문제 + 보기 → 정상 union 병합.

    회귀 스냅샷: merged 길이 1, original_candidate_boxes 길이 2,
    crop_box 가 두 박스의 union 과 정확히 일치(하드코딩 스냅샷).
    """
    page_image_path = _create_page_image(tmp_path / "page.png")
    problem = ProblemCropCandidate(
        page_number=1,
        problem_number=None,
        elective_subject="common",
        crop_box={"x": 60, "y": 180, "width": 680, "height": 220},  # y1=180, y2=400
        image_path=str(page_image_path),
    )
    answer = ProblemCropCandidate(
        page_number=1,
        problem_number=None,
        elective_subject="common",
        crop_box={"x": 60, "y": 430, "width": 680, "height": 140},  # y1=430, y2=570
        image_path=str(page_image_path),
    )

    merged = merge_classified_candidates(
        page_image_path=page_image_path,
        page_number=1,
        candidates=[problem, answer],
        classifications=[
            _classification(save=True, merge=False, number=1),
            _classification(save=True, merge=True),
        ],
    )

    assert len(merged) == 1
    assert len(merged[0]["original_candidate_boxes"]) == 2
    # union 스냅샷: x=60, y=180, width=680, height=570-180=390
    assert merged[0]["crop_box"] == {"x": 60, "y": 180, "width": 680, "height": 390}


def test_heavy_overlap_is_not_merged_and_kept_separate(tmp_path):
    """HEAVY 관계(iou >= IOU_SIBLING_MAX, 포함 아님): 병합 보류 → 분리 유지.

    merged 길이 2, 각 crop_box 가 union 되지 않고 원본을 그대로 유지해야 한다.
    box1 y1=100~500, box2 y1=250~650 → iou≈0.45(>=0.15), overlap_ratio=0.625(<0.80).
    """
    page_image_path = _create_page_image(tmp_path / "page.png")
    box1 = {"x": 60, "y": 100, "width": 600, "height": 400}  # y1=100, y2=500
    box2 = {"x": 60, "y": 250, "width": 600, "height": 400}  # y1=250, y2=650
    prev = ProblemCropCandidate(
        page_number=1,
        problem_number=None,
        elective_subject="common",
        crop_box=box1,
        image_path=str(page_image_path),
    )
    heavy = ProblemCropCandidate(
        page_number=1,
        problem_number=None,
        elective_subject="common",
        crop_box=box2,
        image_path=str(page_image_path),
    )

    merged = merge_classified_candidates(
        page_image_path=page_image_path,
        page_number=1,
        candidates=[prev, heavy],
        classifications=[
            _classification(save=True, merge=False, number=1),
            _classification(save=True, merge=True),  # 병합 요청이지만 HEAVY라 보류
        ],
    )

    assert len(merged) == 2
    # 각 박스는 union 되지 않고 원본 유지.
    assert merged[0]["crop_box"] == box1
    assert merged[1]["crop_box"] == box2
    # 각 문제는 자기 원본만 보유(과병합 없음).
    assert merged[0]["original_candidate_boxes"] == [box1]
    assert merged[1]["original_candidate_boxes"] == [box2]


def test_contained_candidate_is_absorbed_into_previous(tmp_path):
    """CONTAINED 관계(작은 쪽 80%+ 포함): 흡수 → 병합.

    merged 길이 1, crop_box 가 두 박스를 감싸는 union(=바깥 큰 박스)과 일치.
    big 이 small 을 완전히 포함하므로 overlap_ratio=1.0 >= 0.80 → CONTAINED.
    """
    page_image_path = _create_page_image(tmp_path / "page.png")
    big = {"x": 60, "y": 100, "width": 600, "height": 600}  # y1=100, y2=700
    small = {"x": 100, "y": 200, "width": 200, "height": 200}  # 완전 포함
    prev = ProblemCropCandidate(
        page_number=1,
        problem_number=None,
        elective_subject="common",
        crop_box=big,
        image_path=str(page_image_path),
    )
    inner = ProblemCropCandidate(
        page_number=1,
        problem_number=None,
        elective_subject="common",
        crop_box=small,
        image_path=str(page_image_path),
    )

    merged = merge_classified_candidates(
        page_image_path=page_image_path,
        page_number=1,
        candidates=[prev, inner],
        classifications=[
            _classification(save=True, merge=False, number=1),
            _classification(save=True, merge=True),
        ],
    )

    assert len(merged) == 1
    assert len(merged[0]["original_candidate_boxes"]) == 2
    # union = 바깥 큰 박스 자체(big 이 small 을 포함하므로).
    assert merged[0]["crop_box"] == big


def test_merge_boxes_union_snapshot():
    """DISJOINT union 계산 정확성: 순수 단위 검증(하드코딩 스냅샷).

    `_merge_boxes` 와 `_merge_boxes_guarded`(DISJOINT 경로)가 동일 union 을 낸다.
    """
    first = {"x": 60, "y": 180, "width": 680, "height": 220}  # y2=400
    second = {"x": 60, "y": 430, "width": 680, "height": 140}  # y1=430, y2=570

    # 순수 union.
    assert _merge_boxes(first, second) == {"x": 60, "y": 180, "width": 680, "height": 390}

    # guarded: DISJOINT 이므로 병합(True) + 동일 union.
    box, should_merge = _merge_boxes_guarded(first, second)
    assert should_merge is True
    assert box == {"x": 60, "y": 180, "width": 680, "height": 390}

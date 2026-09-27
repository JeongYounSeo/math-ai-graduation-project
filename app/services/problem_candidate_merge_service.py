import os
from pathlib import Path
from typing import Optional

from app.services.crop_classifier_service import CropClassificationResult
from app.services.problem_crop_service import ProblemCropCandidate
from app.services.region_overlap_validator import CONTAINED, HEAVY, classify_pair
from app.utils.box_geometry import xywh_to_corner


def _debug_enabled() -> bool:
    return os.getenv("DEBUG_CROP", "").lower() in {"1", "true", "yes"}


def merge_classified_candidates(
    *,
    page_image_path: Path,
    page_number: int,
    candidates: list[ProblemCropCandidate],
    classifications: list[CropClassificationResult | dict],
) -> list[dict]:
    merged: list[dict] = []
    previous_problem: Optional[dict] = None

    for candidate, classification in zip(candidates, classifications):
        result = classification.to_dict() if isinstance(classification, CropClassificationResult) else classification

        if _debug_enabled():
            print(
                f"[crop-classifier] {Path(candidate.image_path).name} => {result['candidate_type']}, save={result['should_save_as_problem']}, number={result['problem_number']}"
            )

        if not result.get("should_save_as_problem", False):
            continue

        if result.get("should_merge_with_previous", False) and previous_problem is not None:
            # IoU 가드: union 전에 관계를 판정한다(정본 설계 §7).
            # CONTAINED/DISJOINT/TOUCHING -> 병합, HEAVY -> 병합 보류(분리 유지).
            merged_box, should_merge = _merge_boxes_guarded(
                previous_problem["crop_box"], candidate.crop_box
            )
            if should_merge:
                previous_problem["crop_box"] = merged_box
                previous_problem["original_candidate_boxes"].append(candidate.crop_box)
                continue
            # HEAVY: 과병합 방지 위해 흡수하지 않고 별도 새 문제로 분리 유지한다.
            if _debug_enabled():
                print(
                    f"[crop-merge] HEAVY overlap -> 병합 보류(분리 유지): "
                    f"{Path(candidate.image_path).name}"
                )
            # (아래 새 문제 등록 경로로 진행)

        current_problem = {
            "page_number": page_number,
            # crop 단계에서 감지한 번호(candidate)를 classifier 값보다 우선한다
            # (2026-09-25 번호 기반 crop 연결). candidate 에 없을 때만 classifier 값 사용.
            "problem_number": (
                candidate.problem_number
                if candidate.problem_number is not None
                else result.get("problem_number")
            ),
            "elective_subject": candidate.elective_subject,
            "crop_method": candidate.crop_method,
            "crop_box": {**candidate.crop_box},
            "original_candidate_boxes": [candidate.crop_box],
            "status": "unclassified",
            "source_image_path": str(page_image_path),
        }
        merged.append(current_problem)
        previous_problem = current_problem

    return merged


def _merge_boxes(first: dict, second: dict) -> dict:
    """두 xywh box 를 무조건 union 한 순수 함수(하위호환 유지).

    IoU 가드 없이 union 만 계산한다. 병합 여부 판정이 필요하면
    :func:`_merge_boxes_guarded` 를 사용한다.
    """
    x = min(first["x"], second["x"])
    y = min(first["y"], second["y"])
    x2 = max(first["x"] + first["width"], second["x"] + second["width"])
    y2 = max(first["y"] + first["height"], second["y"] + second["height"])
    return {"x": x, "y": y, "width": x2 - x, "height": y2 - y}


def _merge_boxes_guarded(first: dict, second: dict) -> tuple[dict, bool]:
    """IoU 가드가 붙은 병합 판정(정본 설계 §7).

    두 xywh box 의 관계를 :func:`classify_pair` 로 판정한다(xywh -> corner 변환).
    반환: ``(결과박스, should_merge)``.

    - CONTAINED (한쪽이 다른 쪽을 80%+ 포함): union 결과를 반환하고 병합(흡수).
      (union 은 사실상 더 큰 바깥 박스를 감싸는 박스가 된다.)
    - HEAVY (iou >= IOU_SIBLING_MAX 이지만 포함은 아님): 병합 보류.
      union 하지 않고 첫 박스를 그대로 돌려주며 should_merge=False 신호를 준다.
    - DISJOINT / TOUCHING: 기존과 동일하게 union 하여 병합.
    """
    rel = classify_pair(xywh_to_corner(first), xywh_to_corner(second))
    if rel == HEAVY:
        # 병합 보류(분리 유지). 결과 박스는 사용되지 않으므로 first 를 그대로 반환.
        return {**first}, False
    if rel == CONTAINED:
        # 흡수: 더 큰 박스를 감싸는 union 을 반환.
        return _merge_boxes(first, second), True
    # DISJOINT / TOUCHING: 정상 union.
    return _merge_boxes(first, second), True

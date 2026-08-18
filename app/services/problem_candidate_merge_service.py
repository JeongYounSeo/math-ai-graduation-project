import os
from pathlib import Path
from typing import Optional

from app.services.crop_classifier_service import CropClassificationResult
from app.services.problem_crop_service import ProblemCropCandidate


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

        if os.getenv("DEBUG_CROP", "").lower() in {"1", "true", "yes"}:
            print(
                f"[crop-classifier] {Path(candidate.image_path).name} => {result['candidate_type']}, save={result['should_save_as_problem']}, number={result['problem_number']}"
            )

        if not result.get("should_save_as_problem", False):
            continue

        if result.get("should_merge_with_previous", False) and previous_problem is not None:
            previous_problem["crop_box"] = _merge_boxes(previous_problem["crop_box"], candidate.crop_box)
            previous_problem["original_candidate_boxes"].append(candidate.crop_box)
            continue

        current_problem = {
            "page_number": page_number,
            "problem_number": result.get("problem_number"),
            "elective_subject": candidate.elective_subject,
            "crop_box": {**candidate.crop_box},
            "original_candidate_boxes": [candidate.crop_box],
            "status": "unclassified",
            "source_image_path": str(page_image_path),
        }
        merged.append(current_problem)
        previous_problem = current_problem

    return merged


def _merge_boxes(first: dict, second: dict) -> dict:
    x = min(first["x"], second["x"])
    y = min(first["y"], second["y"])
    x2 = max(first["x"] + first["width"], second["x"] + second["width"])
    y2 = max(first["y"] + first["height"], second["y"] + second["height"])
    return {"x": x, "y": y, "width": x2 - x, "height": y2 - y}

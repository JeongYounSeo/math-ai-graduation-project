from pathlib import Path

from PIL import Image

from app.models.problem import Problem
from app.services.problem_crop_service import ProblemCropCandidate


def _create_page_image(path: Path) -> Path:
    image = Image.new("RGB", (800, 1000), "white")
    image.save(path)
    return path


def test_header_and_blank_candidates_are_not_saved_as_problems(tmp_path):
    from app.services.problem_candidate_merge_service import merge_classified_candidates

    page_image_path = _create_page_image(tmp_path / "page.png")
    header_candidate = ProblemCropCandidate(
        page_number=1,
        problem_number=None,
        elective_subject="common",
        crop_box={"x": 40, "y": 30, "width": 720, "height": 80},
        image_path=str(page_image_path),
    )
    blank_candidate = ProblemCropCandidate(
        page_number=1,
        problem_number=None,
        elective_subject="common",
        crop_box={"x": 40, "y": 900, "width": 720, "height": 60},
        image_path=str(page_image_path),
    )

    merged = merge_classified_candidates(
        page_image_path=page_image_path,
        page_number=1,
        candidates=[header_candidate, blank_candidate],
        classifications=[
            {"candidate_type": "header", "is_problem_related": False, "problem_number": None, "score": None, "should_save_as_problem": False, "should_merge_with_previous": False, "confidence": 0.95, "reason": "header"},
            {"candidate_type": "blank", "is_problem_related": False, "problem_number": None, "score": None, "should_save_as_problem": False, "should_merge_with_previous": False, "confidence": 0.99, "reason": "blank"},
        ],
    )

    assert merged == []


def test_problem_candidate_is_saved_as_unclassified_problem(tmp_path):
    from app.services.problem_candidate_merge_service import merge_classified_candidates

    page_image_path = _create_page_image(tmp_path / "page.png")
    problem_candidate = ProblemCropCandidate(
        page_number=1,
        problem_number=None,
        elective_subject="common",
        crop_box={"x": 60, "y": 180, "width": 680, "height": 240},
        image_path=str(page_image_path),
    )

    merged = merge_classified_candidates(
        page_image_path=page_image_path,
        page_number=1,
        candidates=[problem_candidate],
        classifications=[
            {"candidate_type": "problem", "is_problem_related": True, "problem_number": 1, "score": None, "should_save_as_problem": True, "should_merge_with_previous": False, "confidence": 0.92, "reason": "problem"},
        ],
    )

    assert len(merged) == 1
    assert merged[0]["problem_number"] == 1
    assert merged[0]["status"] == "unclassified"


def test_answer_choices_are_merged_with_previous_problem(tmp_path):
    from app.services.problem_candidate_merge_service import merge_classified_candidates

    page_image_path = _create_page_image(tmp_path / "page.png")
    problem_candidate = ProblemCropCandidate(
        page_number=1,
        problem_number=None,
        elective_subject="common",
        crop_box={"x": 60, "y": 180, "width": 680, "height": 220},
        image_path=str(page_image_path),
    )
    answer_candidate = ProblemCropCandidate(
        page_number=1,
        problem_number=None,
        elective_subject="common",
        crop_box={"x": 60, "y": 430, "width": 680, "height": 140},
        image_path=str(page_image_path),
    )

    merged = merge_classified_candidates(
        page_image_path=page_image_path,
        page_number=1,
        candidates=[problem_candidate, answer_candidate],
        classifications=[
            {"candidate_type": "problem", "is_problem_related": True, "problem_number": 2, "score": None, "should_save_as_problem": True, "should_merge_with_previous": False, "confidence": 0.94, "reason": "problem"},
            {"candidate_type": "answer_choices", "is_problem_related": True, "problem_number": None, "score": None, "should_save_as_problem": True, "should_merge_with_previous": True, "confidence": 0.9, "reason": "choices"},
        ],
    )

    assert len(merged) == 1
    assert merged[0]["problem_number"] == 2
    assert len(merged[0]["original_candidate_boxes"]) == 2

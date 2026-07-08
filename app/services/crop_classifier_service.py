from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import os


@dataclass
class CropClassificationResult:
    candidate_type: str
    is_problem_related: bool
    problem_number: Optional[int]
    score: Optional[float]
    should_save_as_problem: bool
    should_merge_with_previous: bool
    confidence: float
    reason: str

    def to_dict(self) -> dict:
        return {
            "candidate_type": self.candidate_type,
            "is_problem_related": self.is_problem_related,
            "problem_number": self.problem_number,
            "score": self.score,
            "should_save_as_problem": self.should_save_as_problem,
            "should_merge_with_previous": self.should_merge_with_previous,
            "confidence": self.confidence,
            "reason": self.reason,
        }


class CropClassifier:
    def classify(self, image_path: Path, metadata: dict) -> CropClassificationResult:
        raise NotImplementedError


class MockCropClassifier(CropClassifier):
    def classify(self, image_path: Path, metadata: dict) -> CropClassificationResult:
        crop_box = metadata.get("crop_box", {})
        y = int(crop_box.get("y", 0))
        height = int(crop_box.get("height", 0))
        x = int(crop_box.get("x", 0))
        width = int(crop_box.get("width", 0))

        if height < 80:
            return CropClassificationResult(
                candidate_type="blank",
                is_problem_related=False,
                problem_number=None,
                score=None,
                should_save_as_problem=False,
                should_merge_with_previous=False,
                confidence=0.95,
                reason="too small",
            )

        if y < 60 and height < 120:
            return CropClassificationResult(
                candidate_type="header",
                is_problem_related=False,
                problem_number=None,
                score=None,
                should_save_as_problem=False,
                should_merge_with_previous=False,
                confidence=0.9,
                reason="top region appears to be a header",
            )

        if y + height > 900 and height < 150:
            return CropClassificationResult(
                candidate_type="footer",
                is_problem_related=False,
                problem_number=None,
                score=None,
                should_save_as_problem=False,
                should_merge_with_previous=False,
                confidence=0.9,
                reason="bottom page number region",
            )

        if height < 150 and width > 300:
            return CropClassificationResult(
                candidate_type="answer_choices",
                is_problem_related=True,
                problem_number=None,
                score=None,
                should_save_as_problem=True,
                should_merge_with_previous=True,
                confidence=0.8,
                reason="likely answer choices",
            )

        problem_number = None
        if y < 250 and width > 200:
            problem_number = 1

        return CropClassificationResult(
            candidate_type="problem",
            is_problem_related=True,
            problem_number=problem_number,
            score=None,
            should_save_as_problem=True,
            should_merge_with_previous=False,
            confidence=0.75,
            reason="default problem-like crop",
        )


class VisionLLMCropClassifier(CropClassifier):
    def classify(self, image_path: Path, metadata: dict) -> CropClassificationResult:
        raise NotImplementedError("Vision LLM integration is not implemented yet")

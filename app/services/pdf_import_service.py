import os
from pathlib import Path
from typing import List
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.storage import get_page_storage_dir, get_pdf_storage_path, get_problem_storage_dir
from app.models.problem import Problem
from app.models.source_pdf import SourcePDF
from app.repositories.problem_repository import ProblemRepository
from app.repositories.source_pdf_repository import SourcePDFRepository
from app.services.page_render_service import PageRenderService
from app.services.problem_candidate_merge_service import merge_classified_candidates
from app.services.problem_crop_service import crop_problem_candidates
from app.services.crop_classifier_service import MockCropClassifier
from app.services.problem_text_filter_service import ProblemTextFilter, extract_text_from_pdf_region
from app.utils.image_utils import draw_boxes_overlay, get_debug_output_path, save_debug_overlay


class PDFImportService:
    def __init__(self, db: Session):
        self.db = db
        self.page_render_service = PageRenderService()
        self.problem_repository = ProblemRepository(db)
        self.source_pdf_repository = SourcePDFRepository(db)
        self.crop_classifier = MockCropClassifier()
        self.text_filter = ProblemTextFilter()

    def import_pdf(self, uploaded_file, original_filename: str) -> dict:
        source_pdf_id = f"PDF_{uuid4().hex[:8].upper()}"
        stored_filename = f"{source_pdf_id}.pdf"
        pdf_path = get_pdf_storage_path(source_pdf_id)
        with pdf_path.open("wb") as buffer:
            buffer.write(uploaded_file.file.read())

        source_pdf = self.source_pdf_repository.create(
            {
                "source_pdf_id": source_pdf_id,
                "original_filename": original_filename,
                "stored_filename": stored_filename,
                "file_path": str(pdf_path),
                "total_pages": 0,
                "status": "uploaded",
            }
        )

        rendered_paths = self.page_render_service.render_pdf_pages(pdf_path, source_pdf_id)
        source_pdf.total_pages = len(rendered_paths)
        source_pdf.status = "rendered"
        self.db.commit()

        debug_enabled = os.getenv("DEBUG_CROP", "").lower() in {"1", "true", "yes"}
        strict_text_filter = os.getenv("STRICT_TEXT_FILTER", "").lower() in {"1", "true", "yes"}

        problem_candidates = []
        problem_count = 0
        for page_number, (page_image_path, page_obj) in enumerate(rendered_paths, start=1):
            raw_candidates = crop_problem_candidates(page_image_path, page_number, page=page_obj)

            from PIL import Image

            with Image.open(page_image_path) as page_image:
                image_width, image_height = page_image.size

            classifications = []
            for candidate in raw_candidates:
                metadata = {
                    "page_number": page_number,
                    "crop_box": candidate.crop_box,
                    "image_path": str(page_image_path),
                    "width": image_width,
                    "height": image_height,
                }
                classification = self.crop_classifier.classify(page_image_path, metadata)
                classifications.append(classification)

            merged_results = merge_classified_candidates(
                page_image_path=page_image_path,
                page_number=page_number,
                candidates=raw_candidates,
                classifications=classifications,
            )

            debug_kept_boxes: list[dict] = []
            debug_uncertain_boxes: list[dict] = []
            debug_dropped_boxes: list[dict] = []

            for candidate_index, merged_result in enumerate(merged_results, start=1):
                crop_box = merged_result["crop_box"]
                extracted_text = extract_text_from_pdf_region(page_obj, crop_box, (image_width, image_height))
                filter_result = self.text_filter.evaluate_text(extracted_text)

                text_extraction_failed = not extracted_text.strip()
                if text_extraction_failed:
                    should_save = not strict_text_filter
                    reason = "no text extracted" if not strict_text_filter else "no text extracted (strict mode)"
                else:
                    should_save = filter_result.should_save
                    reason = filter_result.reason

                print(
                    f"[text-filter] page={page_number} candidate={candidate_index} "
                    f"save={str(should_save).lower()} score={filter_result.score} "
                    f"matches={filter_result.positive_matches} "
                    f"instruction_removed={str(filter_result.instruction_section_removed).lower()}"
                )

                if not should_save:
                    print(f"[text-filter] page={page_number} candidate={candidate_index} dropped reason='{reason}'")
                    if debug_enabled:
                        debug_dropped_boxes.append(_to_corner_box(crop_box))
                    continue

                if debug_enabled:
                    if text_extraction_failed:
                        debug_uncertain_boxes.append(_to_corner_box(crop_box))
                    else:
                        debug_kept_boxes.append(_to_corner_box(crop_box))

                problem_count += 1
                problem_image_path = self._save_problem_image(
                    page_image_path,
                    crop_box,
                    source_pdf_id,
                    problem_count,
                    merged_result.get("original_candidate_boxes", []),
                )
                problem = self.problem_repository.create_from_pdf(
                    source_pdf_id=source_pdf_id,
                    page_number=page_number,
                    problem_number=merged_result.get("problem_number"),
                    elective_subject=merged_result.get("elective_subject", "common"),
                    problem_image_path=problem_image_path,
                    page_image_path=str(page_image_path),
                    crop_box=crop_box,
                    status="unclassified",
                    original_candidate_boxes=merged_result.get("original_candidate_boxes"),
                    raw_ocr_text=filter_result.extracted_text or None,
                )
                problem_candidates.append(problem)

            if debug_enabled:
                self._save_text_filter_debug_image(
                    page_image_path,
                    page_number,
                    debug_kept_boxes,
                    debug_uncertain_boxes,
                    debug_dropped_boxes,
                )

        source_pdf.status = "imported"
        self.db.commit()

        return {
            "source_pdf_id": source_pdf_id,
            "total_pages": len(rendered_paths),
            "imported_problem_count": len(problem_candidates),
            "status": "imported",
        }

    def _save_problem_image(self, page_image_path: Path, crop_box: dict, source_pdf_id: str, counter: int, original_candidate_boxes: list | None = None) -> str:
        problem_dir = get_problem_storage_dir(source_pdf_id)
        image_path = problem_dir / f"P_{counter:06d}.png"
        from PIL import Image
        page_image = Image.open(page_image_path)
        cropped = page_image.crop(
            (
                crop_box["x"],
                crop_box["y"],
                crop_box["x"] + crop_box["width"],
                crop_box["y"] + crop_box["height"],
            )
        )
        cropped.save(image_path)
        return str(image_path)

    def _save_text_filter_debug_image(
        self,
        page_image_path: Path,
        page_number: int,
        kept_boxes: list,
        uncertain_boxes: list,
        dropped_boxes: list,
    ) -> None:
        """DEBUG_CROP=true일 때 텍스트 필터 결과를 색으로 구분해 저장한다.

        green = saved problem, yellow = uncertain (텍스트 추출 실패로 fallback 저장됨),
        gray = dropped (문제답지 않다고 판단해 저장하지 않음).
        """
        import cv2

        image = cv2.imread(str(page_image_path), cv2.IMREAD_COLOR)
        if image is None:
            return

        overlay = draw_boxes_overlay(image, dropped_boxes, color=(128, 128, 128), label_prefix="d")
        overlay = draw_boxes_overlay(overlay, uncertain_boxes, color=(0, 220, 220), label_prefix="u")
        overlay = draw_boxes_overlay(overlay, kept_boxes, color=(0, 200, 0), label_prefix="k")
        save_debug_overlay(overlay, get_debug_output_path(page_image_path, page_number, "textfilter"))


def _to_corner_box(crop_box: dict) -> dict:
    """{x, y, width, height} 형태를 draw_boxes_overlay가 기대하는
    {x1, y1, x2, y2} 형태로 변환한다."""
    return {
        "x1": crop_box["x"],
        "y1": crop_box["y"],
        "x2": crop_box["x"] + crop_box["width"],
        "y2": crop_box["y"] + crop_box["height"],
    }

import logging
import os
from pathlib import Path
from types import SimpleNamespace
from typing import List, Literal
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.storage import get_page_storage_dir, get_pdf_storage_path, get_problem_storage_dir
from app.models.problem import Problem, ProblemStatus
from app.models.source_pdf import SourcePDF
from app.repositories.problem_repository import ProblemRepository
from app.repositories.source_pdf_repository import SourcePDFRepository
from app.services.page_render_service import PageRenderService
from app.services.problem_candidate_merge_service import merge_classified_candidates
from app.services.problem_crop_service import crop_page_with_gemini, crop_problem_candidates
from app.services.gemini_page_crop_client import GeminiPageCropClient
from app.services.problem_region_extraction_service import ProblemRegionExtractionService
from app.services.problem_ocr_apply_service import ProblemOcrApplyService
from app.models.problem_region import RegionType
from app.repositories.problem_region_repository import ProblemRegionRepository
from app.repositories.problem_region_item_repository import ProblemRegionItemRepository
from app.services.crop_classifier_service import MockCropClassifier
from app.services.problem_text_filter_service import ProblemTextFilter, extract_text_from_pdf_region
from app.services.region_overlap_validator import Region, validate_and_resolve
from app.utils.box_geometry import corner_to_xywh, xywh_to_corner
from app.utils.image_utils import draw_boxes_overlay, get_debug_output_path, save_debug_overlay

logger = logging.getLogger(__name__)


class PDFImportService:
    def __init__(self, db: Session):
        self.db = db
        self.page_render_service = PageRenderService()
        self.problem_repository = ProblemRepository(db)
        self.source_pdf_repository = SourcePDFRepository(db)
        self.crop_classifier = MockCropClassifier()
        self.text_filter = ProblemTextFilter()
        self.gemini_crop_client = GeminiPageCropClient(settings.GEMINI_API_KEY, settings.GEMINI_CROP_MODEL)
        # 자격증명이 없으면 스텁 폴백(Req 6)으로 네트워크 호출 없이 성공 반환하므로
        # 임포트 파이프라인은 테스트/로컬 환경에서도 안전하게 동작한다.
        self.region_extraction_service = ProblemRegionExtractionService(db)

    def reprocess_source_pdf(self, source_pdf_id: str, crop_mode: Literal["a_only", "auto"] = "a_only") -> dict:
        """Reimport a stored PDF as a new source, preserving the original rows.

        This reruns cropping without per-problem Vision region calls.
        The returned source ID identifies the reviewable replacement dataset.
        """
        source = self.source_pdf_repository.get_by_id(source_pdf_id)
        if source is None:
            raise LookupError(f"source PDF not found: {source_pdf_id}")
        pdf_path = Path(source.file_path)
        if not pdf_path.is_file():
            raise FileNotFoundError(f"stored PDF not found: {pdf_path}")
        if crop_mode == "auto" and not self.gemini_crop_client.is_configured():
            raise ValueError("GEMINI_API_KEY is required for auto crop")

        with pdf_path.open("rb") as file_obj:
            result = self.import_pdf(
                SimpleNamespace(file=file_obj), source.original_filename,
                extract_regions=False, crop_mode=crop_mode,
            )
        reprocessed = self.source_pdf_repository.get_by_id(result["source_pdf_id"])
        for field in ("exam_name", "year", "month", "grade", "subject"):
            setattr(reprocessed, field, getattr(source, field))
        self.db.commit()
        return {"reprocessed_from_source_pdf_id": source_pdf_id, **result}

    def import_pdf(
        self, uploaded_file, original_filename: str, *,
        extract_regions: bool = True, crop_mode: Literal["a_only", "auto"] = "a_only",
    ) -> dict:
        if crop_mode == "auto" and not self.gemini_crop_client.is_configured():
            raise ValueError("GEMINI_API_KEY is required for auto crop")
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
        numbered_problem_count = 0
        page_reports: list[dict] = []
        for page_number, (page_image_path, page_obj) in enumerate(rendered_paths, start=1):
            page_saved_before = problem_count
            if crop_mode == "auto":
                page_result = crop_page_with_gemini(
                    page_image_path, page_number, page_obj, self.gemini_crop_client
                )
                raw_candidates = page_result.candidates
                page_reports.append({
                    "page_number": page_number,
                    "method": page_result.method,
                    "needs_review": page_result.needs_review,
                    "reason": page_result.reason,
                    "input_tokens": page_result.input_tokens,
                    "output_tokens": page_result.output_tokens,
                    "crop_count": len(raw_candidates),
                })
            else:
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
                    "problem_number": candidate.problem_number,
                    "crop_method": candidate.crop_method,
                }
                classification = self.crop_classifier.classify(page_image_path, metadata)
                classifications.append(classification)

            merged_results = merge_classified_candidates(
                page_image_path=page_image_path,
                page_number=page_number,
                candidates=raw_candidates,
                classifications=classifications,
            )

            # ---- 훅 1 (candidates): 겹침 검증 (플래그 off 기본, 회귀 0) ----
            # 플래그 off면 merged_results를 그대로 반환(검증기 미호출).
            merged_results = self._apply_candidate_overlap_validation(
                merged_results, image_width, image_height
            )

            debug_kept_boxes: list[dict] = []
            debug_uncertain_boxes: list[dict] = []
            debug_dropped_boxes: list[dict] = []

            for candidate_index, merged_result in enumerate(merged_results, start=1):
                crop_box = merged_result["crop_box"]
                extracted_text = extract_text_from_pdf_region(page_obj, crop_box, (image_width, image_height))
                filter_result = self.text_filter.evaluate_text(extracted_text)

                text_extraction_failed = not extracted_text.strip()
                if crop_mode == "auto" and page_result.method in {"number_verified", "gemini"}:
                    should_save = True
                    reason = "Gemini-verified page crop"
                elif text_extraction_failed:
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
                if problem.problem_number is not None:
                    numbered_problem_count += 1

                # A안 재처리는 바깥 crop만 갱신한다. Vision 호출 없이 full_problem
                # 영역을 만들어 새 결과를 독립적으로 검토할 수 있게 한다.
                if not extract_regions:
                    ProblemOcrApplyService(self.db).apply_ocr_result(
                        problem.id, {"crop_box": crop_box}
                    )
                    continue

                # ---- Task 11.1: 영역 추출 후처리 (Req 7.3, 7.4) ----
                # 한 문제 이미지의 추출 실패(재시도 소진 포함)가 예외로 전체 임포트
                # 파이프라인을 중단시키지 않도록 try/except로 격리한다. 실패한 문제만
                # "failed"로 표시하고 남은 문제 이미지는 계속 처리한다.
                try:
                    extraction_result = self.region_extraction_service.extract_regions(problem)
                    # 스텁 폴백(자격증명 부재)은 success=True로 반환되므로 failed 처리하지
                    # 않는다. success=False(재시도 소진/malformed/타임아웃 등)일 때만
                    # 해당 문제를 failed로 표시한다.
                    if not extraction_result.success:
                        self._mark_problem_failed(problem)
                        logger.warning(
                            "region extraction unsuccessful for problem %s: type=%s errors=%s",
                            problem.id,
                            extraction_result.failure_type,
                            extraction_result.errors,
                        )
                    else:
                        # ---- 훅 2 (regions): 겹침 검증 (플래그 off 기본, 회귀 0) ----
                        # 플래그 off면 아무 것도 하지 않는다(기존 경로 그대로).
                        self._apply_region_overlap_validation(problem)
                        # ---- 신규: full_problem region 자동 생성 + 객관식 보기 반영 ----
                        # crop_box 만 있으면 Vision 없이도 full_problem 은 항상 생성된다.
                        # CHOICE_BOX region 이 있으면 그 items 텍스트를 choices 로 조립.
                        # Vision 미연동(스텁)이면 choices 가 비어 보기 저장은 skip 된다(회귀 0).
                        try:
                            ocr_result = self._build_ocr_result_from_regions(problem)
                            ProblemOcrApplyService(self.db).apply_ocr_result(
                                problem.id, ocr_result
                            )
                        except Exception as exc:
                            logger.warning(
                                "apply_ocr_result failed for problem %s: %s",
                                problem.id,
                                exc,
                            )
                except Exception as exc:
                    # extract_regions가 예외를 던져도 파이프라인을 중단하지 않는다(Req 7.3).
                    logger.warning(
                        "region extraction raised for problem %s: %s", problem.id, exc
                    )
                    self._mark_problem_failed(problem)
                    # 재발생시키지 않음 — 남은 문제 이미지 계속 처리 (Req 7.4)

            if debug_enabled:
                self._save_text_filter_debug_image(
                    page_image_path,
                    page_number,
                    debug_kept_boxes,
                    debug_uncertain_boxes,
                    debug_dropped_boxes,
                )

            if crop_mode == "auto":
                page_report = page_reports[-1]
                page_report["saved_count"] = problem_count - page_saved_before
                if page_report["saved_count"] != page_report["crop_count"]:
                    page_report["needs_review"] = True
                    page_report["reason"] = (
                        f"{page_report['reason']}; " if page_report["reason"] else ""
                    ) + "some crop candidates were not saved"

        final_status = "needs_review" if any(report["needs_review"] for report in page_reports) else "imported"
        source_pdf.status = final_status
        self.db.commit()

        return {
            "source_pdf_id": source_pdf_id,
            "total_pages": len(rendered_paths),
            "imported_problem_count": len(problem_candidates),
            "numbered_problem_count": numbered_problem_count,
            "status": final_status,
            **({"crop_mode": crop_mode, "page_reports": page_reports} if crop_mode == "auto" else {}),
        }

    def _apply_candidate_overlap_validation(
        self, merged_results: List[dict], page_w: float, page_h: float
    ) -> List[dict]:
        """훅 1: crop 후보(merged_results)에 겹침 검증기(mode="candidates")를 적용한다.

        - 플래그(``ENABLE_REGION_OVERLAP_VALIDATION``) off(기본)면 **아무 것도 하지
          않고** 입력 merged_results 를 그대로 반환한다(검증기 미호출 → 회귀 0).
        - 플래그 on이면 각 항목의 xywh ``crop_box`` 를 corner 로 변환해 검증기에
          넘기고, 보정된 corner 를 다시 xywh 로 되돌려 crop_box 를 갱신한다.
          reject 로 사라진 후보는 merged_results 에서도 제외하되, dict 의 나머지
          필드(problem_number, elective_subject, original_candidate_boxes 등)는
          보존한다(Region.id 에 원본 index 를 실어 매핑).
        - 훅 전체를 try/except 로 감싸 예외 시 원본 merged_results 유지(fail-open)
          + warning 1회. 파이프라인을 절대 중단시키지 않는다.
        """
        if not settings.ENABLE_REGION_OVERLAP_VALIDATION:
            # 플래그 off: 회귀 0. 검증기를 호출조차 하지 않는다.
            return merged_results

        if not merged_results:
            return merged_results

        try:
            regions: list[Region] = []
            for index, item in enumerate(merged_results):
                x1, y1, x2, y2 = xywh_to_corner(item["crop_box"])
                regions.append(
                    Region(
                        x1=x1,
                        y1=y1,
                        x2=x2,
                        y2=y2,
                        id=index,  # 원본 merged_results index 매핑용.
                    )
                )

            result = validate_and_resolve(
                regions, page_w, page_h, mode="candidates"
            )

            # 보정된 Region 을 원본 index 기준으로 되돌려 반영.
            new_results: list[dict] = []
            for region in result.regions:
                idx = region.id
                if idx is None or idx < 0 or idx >= len(merged_results):
                    # 매핑 불가한 region 은 건너뛴다(방어적).
                    continue
                original = merged_results[idx]
                updated = dict(original)  # 부가 필드 보존.
                updated["crop_box"] = corner_to_xywh(
                    region.x1, region.y1, region.x2, region.y2
                )
                new_results.append(updated)

            # reject 로 사라진 index 는 new_results 에서 자연히 제외된다.
            return new_results
        except Exception as exc:  # noqa: BLE001 — fail-open.
            logger.warning(
                "candidate overlap validation 훅 실패 → 원본 유지(fail-open): %s", exc
            )
            return merged_results

    def _build_ocr_result_from_regions(self, problem: Problem) -> dict:
        """이미 추출된 ProblemRegion 에서 apply_ocr_result 용 result dict 를 조립한다.

        두 세대의 보기 표현을 모두 지원한다(우선순위 순):

        1. **신규 choice_option 방식(설계 §5)**: 각 보기가 별도 region
           (``region_type == "choice_option"``)으로 저장되고 텍스트는 region 의
           ocr_text/latex_text 에 담긴다. 2개 이상이면 이 방식을 우선 사용한다.
           정렬은 order_index → get_box() 의 top(y1) 순(둘 다 없으면 원 순서 유지).
        2. **기존 CHOICE_BOX 방식**: 보기 묶음 1개 region 아래 items(①②③④⑤).
           choice_option 이 없을 때만 fallback 으로 사용한다.

        어느 쪽도 없으면 ``choices`` 를 넣지 않아 보기 저장이 skip 된다(회귀 0).
        ``crop_box`` 는 항상 problem.crop_box 를 넘겨 full_problem region 생성을 보장.
        """
        result: dict = {"crop_box": problem.crop_box}

        region_repo = ProblemRegionRepository(self.db)
        item_repo = ProblemRegionItemRepository(self.db)
        regions = region_repo.get_by_problem_id(problem.id)

        # 1) 신규 choice_option 방식 우선.
        choices = self._choices_from_choice_options(regions)

        # 2) 없으면 기존 CHOICE_BOX + items 로 fallback.
        if not choices:
            choices = self._choices_from_choice_box(regions, item_repo)

        if choices:
            result["answer_type"] = "multiple_choice"
            result["choices"] = choices

        return result

    @staticmethod
    def _choices_from_choice_options(regions) -> list:
        """choice_option region 들의 텍스트를 순서대로 뽑아 choices 리스트로 만든다.

        정렬 키: (order_index 가 있으면 그 값, 없으면 큰 수) → get_box() top(y1).
        텍스트는 latex_text 를 우선, 없으면 ocr_text 를 쓴다. 2개 미만이면 [].
        """
        opts = [
            r for r in regions if r.region_type == RegionType.CHOICE_OPTION.value
        ]
        if len(opts) < 2:
            return []

        def sort_key(r):
            box = r.get_box()
            top = box[1] if box else 0.0
            oi = r.order_index if r.order_index is not None else 10**9
            return (oi, top)

        choices = []
        for r in sorted(opts, key=sort_key):
            text = r.latex_text or r.ocr_text
            if text:
                choices.append(text)
        return choices

    @staticmethod
    def _choices_from_choice_box(regions, item_repo) -> list:
        """기존 CHOICE_BOX region 의 items 를 order_index 순으로 뽑아 choices 로 만든다."""
        for r in regions:
            if r.region_type == RegionType.CHOICE_BOX.value:
                items = item_repo.get_by_region_id(r.id)
                return [
                    it.text
                    for it in sorted(items, key=lambda x: x.order_index)
                    if it.text
                ]
        return []

    def _apply_region_overlap_validation(self, problem: Problem) -> None:
        """훅 2: 한 problem 에 속한 ProblemRegion 들에 겹침 검증기(mode="regions")를 적용.

        - 플래그 off(기본)면 **아무 것도 하지 않는다**(기존 경로 그대로 → 회귀 0).
        - 플래그 on이면:
          * ProblemRegionRepository.get_by_problem_id 로 region 조회.
          * 각 region 의 corner 를 ``get_box()`` 로 얻어 Region 으로 변환
            (region_type/id/parent_region_id 동반).
          * ``validate_and_resolve(mode="regions")`` 로 보정.
          * 보정된 corner 를 ``set_box()`` 로 컬럼+JSON 동시 기록, parent_region_id
            갱신 후 commit.
        - 훅 전체 try/except 로 감싸 예외 시 원본 유지(fail-open) + warning 1회.
          파이프라인 절대 중단 금지.
        """
        if not settings.ENABLE_REGION_OVERLAP_VALIDATION:
            # 플래그 off: 회귀 0. 조회/보정 자체를 하지 않는다.
            return

        try:
            db_regions = self.region_extraction_service.region_repository.get_by_problem_id(
                problem.id
            )
            if not db_regions:
                return

            # 페이지 크기 산출: region 에 기록된 page_width/height 우선, 없으면
            # problem.page_image_path 에서 읽고, 그래도 없으면 아주 큰 값(clamp 영향 X).
            page_w, page_h = self._resolve_page_size(problem, db_regions)

            regions: list[Region] = []
            index_by_id: dict = {}
            for db_region in db_regions:
                corner = db_region.get_box()
                if corner is None:
                    # 좌표가 아예 없는 region 은 보정 대상에서 제외(방어적).
                    continue
                x1, y1, x2, y2 = corner
                regions.append(
                    Region(
                        x1=x1,
                        y1=y1,
                        x2=x2,
                        y2=y2,
                        id=db_region.id,
                        region_type=db_region.region_type,
                        parent_region_id=db_region.parent_region_id,
                    )
                )
                index_by_id[db_region.id] = db_region

            if not regions:
                return

            result = validate_and_resolve(regions, page_w, page_h, mode="regions")

            # 보정 결과를 각 ProblemRegion 에 다시 기록.
            for region in result.regions:
                db_region = index_by_id.get(region.id)
                if db_region is None:
                    continue
                db_region.set_box(
                    (region.x1, region.y1, region.x2, region.y2),
                    page_width=page_w,
                    page_height=page_h,
                )
                db_region.parent_region_id = region.parent_region_id

            self.db.commit()
        except Exception as exc:  # noqa: BLE001 — fail-open.
            self.db.rollback()
            logger.warning(
                "region overlap validation 훅 실패 → 원본 유지(fail-open): %s", exc
            )

    @staticmethod
    def _resolve_page_size(problem: Problem, db_regions: list) -> tuple[float, float]:
        """훅 2용 페이지 크기 산출. region의 page_width/height 우선, 없으면 이미지에서.

        어느 것도 얻지 못하면 아주 큰 기본값을 반환해 page clamp 영향을 없앤다.
        """
        for db_region in db_regions:
            pw = getattr(db_region, "page_width", None)
            ph = getattr(db_region, "page_height", None)
            if pw and ph:
                return float(pw), float(ph)

        page_image_path = getattr(problem, "page_image_path", None)
        if page_image_path:
            try:
                from PIL import Image

                with Image.open(page_image_path) as img:
                    w, h = img.size
                return float(w), float(h)
            except Exception:
                pass

        # clamp 영향이 없도록 아주 큰 기본값.
        return 1_000_000.0, 1_000_000.0

    def _mark_problem_failed(self, problem: Problem) -> None:
        """해당 문제만 failed로 표시하고 커밋한다. 커밋 실패 시 rollback하되
        예외를 전파하지 않아 남은 문제 이미지 처리를 계속한다(Req 7.3, 7.4)."""
        try:
            problem.status = ProblemStatus.FAILED.value
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            logger.warning(
                "failed to mark problem %s as failed: %s", getattr(problem, "id", None), exc
            )

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

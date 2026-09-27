"""Staged outer-crop workflow: propose, review, then persist accepted problems."""

from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone

from PIL import Image
from sqlalchemy.orm import Session

from app.core.config import settings
import app.core.storage as storage
from app.core.storage import get_page_storage_dir, get_pdf_storage_path, get_problem_storage_dir
from app.repositories.crop_review_repository import CropPageReviewRepository, CropProposalRepository
from app.repositories.problem_repository import ProblemRepository
from app.repositories.source_pdf_repository import SourcePDFRepository
from app.services.gemini_page_crop_client import GeminiPageCropClient
from app.services.page_render_service import PageRenderService
from app.services.problem_crop_service import _candidates_from_gemini_boxes
from app.services.problem_ocr_apply_service import ProblemOcrApplyService
from app.services.whitespace_crop_service import propose_whitespace_crops


def _url(path: Path) -> str:
    return "/uploads/" + path.resolve().relative_to(storage.DEFAULT_UPLOAD_ROOT.resolve()).as_posix()


class CropReviewService:
    def __init__(self, db: Session):
        self.db = db
        self.sources = SourcePDFRepository(db)
        self.pages = CropPageReviewRepository(db)
        self.proposals = CropProposalRepository(db)
        self.problems = ProblemRepository(db)
        self.gemini = GeminiPageCropClient(settings.GEMINI_API_KEY, settings.GEMINI_CROP_MODEL)

    def upload(self, uploaded_file, original_filename: str) -> dict:
        source_id = f"PDF_{uuid4().hex[:8].upper()}"
        pdf_path = get_pdf_storage_path(source_id)
        with pdf_path.open("wb") as target:
            while chunk := uploaded_file.file.read(1024 * 1024):
                target.write(chunk)
        try:
            rendered = PageRenderService().render_pdf_pages(pdf_path, source_id)
        except Exception:
            pdf_path.unlink(missing_ok=True)
            raise
        source = self.sources.create({
            "source_pdf_id": source_id, "original_filename": original_filename,
            "stored_filename": pdf_path.name, "file_path": str(pdf_path),
            "total_pages": len(rendered), "status": "awaiting_review",
        })
        return {"source_pdf_id": source.source_pdf_id, "total_pages": source.total_pages,
                "status": source.status}

    def _source(self, source_id: str):
        source = self.sources.get_by_id(source_id)
        if source is None:
            raise LookupError("PDF를 찾을 수 없습니다.")
        if source.status not in {"awaiting_review", "reviewed"}:
            raise ValueError("검토용으로 업로드한 PDF만 이 경로에서 처리할 수 있습니다.")
        return source

    def _page_path(self, source_id: str, page_number: int, total_pages: int) -> Path:
        if page_number < 1 or page_number > total_pages:
            raise LookupError("페이지를 찾을 수 없습니다.")
        path = get_page_storage_dir(source_id) / f"page_{page_number:03d}.png"
        if not path.is_file():
            raise FileNotFoundError(path)
        return path

    def prepare(self, source_id: str, page_number: int, *, retry: bool = False) -> dict:
        source = self._source(source_id)
        if source.status == "reviewed":
            raise ValueError("확정된 PDF는 다시 제안받을 수 없습니다.")
        page_path = self._page_path(source_id, page_number, source.total_pages)
        prior = self.pages.get(source_id, page_number)
        if prior is not None and not retry:
            return self.snapshot(source_id)

        boxes = propose_whitespace_crops(page_path)
        method, verdict, reason = "whitespace", "unverified", "AI 검토를 사용하지 않았습니다."
        input_tokens = output_tokens = 0
        numbered_boxes = [{"crop_box": box, "problem_number": None} for box in boxes]
        if self.gemini.is_configured():
            try:
                decision = self.gemini.inspect(page_path, numbered_boxes)
                usage = decision.get("_usage") or {}
                input_tokens = int(usage.get("total_input_tokens") or 0)
                output_tokens = int(usage.get("total_output_tokens") or 0)
                verdict = decision.get("verdict", "uncertain")
                reason = str(decision.get("reason", ""))
                if verdict == "replace":
                    raw = decision.get("boxes")
                    if raw == []:
                        boxes = []
                        numbered_boxes = []
                        method = "gemini"
                    else:
                        with Image.open(page_path) as image:
                            width, height = image.size
                        replacements = _candidates_from_gemini_boxes(
                            raw, page_path, page_number, width, height, None,
                        )
                        boxes = [candidate.crop_box for candidate in replacements]
                        numbered_boxes = [{"crop_box": candidate.crop_box,
                                           "problem_number": candidate.problem_number}
                                          for candidate in replacements]
                        method = "gemini"
                elif verdict == "accept_a":
                    method = "whitespace_verified"
                else:
                    method = "whitespace_unverified"
            except Exception as exc:
                verdict = "uncertain"
                reason = f"Gemini 검토 실패: {exc}"
                method = "whitespace_unverified"

        row = self.pages.prepare(source_id, page_number, method=method, verdict=verdict,
                                 reason=reason, input_tokens=input_tokens,
                                 output_tokens=output_tokens)
        preview_dir = storage.DEFAULT_UPLOAD_ROOT / "crop-proposals" / source_id
        preview_dir.mkdir(parents=True, exist_ok=True)
        with Image.open(page_path) as image:
            for index, item in enumerate(numbered_boxes, start=1):
                box = item["crop_box"]
                path = preview_dir / f"page_{page_number:03d}_v{row.version}_{index:03d}.png"
                image.crop((box["x"], box["y"], box["x"] + box["width"],
                            box["y"] + box["height"])).save(path)
                self.proposals.add(source_pdf_id=source_id, page_number=page_number,
                                   version=row.version, crop_box=box, preview_image_path=str(path),
                                   problem_number=item["problem_number"], origin=method)
        self.db.commit()
        return self.snapshot(source_id)

    def snapshot(self, source_id: str) -> dict:
        source = self._source(source_id)
        page_rows = {row.page_number: row for row in self.pages.list(source_id)}
        pages = []
        for number in range(1, source.total_pages + 1):
            row = page_rows.get(number)
            image_path = self._page_path(source_id, number, source.total_pages)
            with Image.open(image_path) as page_image:
                image_width, image_height = page_image.size
            items = self.proposals.list(source_id, number, row.version) if row else []
            pages.append({
                "page_number": number, "page_image_url": _url(image_path),
                "image_width": image_width, "image_height": image_height,
                "status": row.status if row else "unprepared",
                "confirmed": bool(row.confirmed) if row else False,
                "version": row.version if row else 0,
                "method": row.method if row else None, "verdict": row.verdict if row else None,
                "reason": row.reason if row else None,
                "input_tokens": row.input_tokens if row else 0,
                "output_tokens": row.output_tokens if row else 0,
                "proposals": [{"id": p.id, "crop_box": p.crop_box,
                               "preview_image_url": _url(Path(p.preview_image_path)),
                               "problem_number": p.problem_number, "origin": p.origin,
                               "decision": p.decision, "problem_id": p.problem_id}
                              for p in items],
            })
        return {"source_pdf_id": source_id, "original_filename": source.original_filename,
                "total_pages": source.total_pages, "status": source.status, "pages": pages}

    def decide(self, proposal_id: int, decision: str) -> dict:
        if decision not in {"accepted", "discarded"}:
            raise ValueError("decision은 accepted 또는 discarded여야 합니다.")
        proposal = self.proposals.get(proposal_id)
        if proposal is None:
            raise LookupError("후보를 찾을 수 없습니다.")
        source = self._source(proposal.source_pdf_id)
        if source.status == "reviewed":
            raise ValueError("확정 후에는 결정을 변경할 수 없습니다.")
        page = self.pages.get(proposal.source_pdf_id, proposal.page_number)
        if page.version != proposal.version:
            raise ValueError("이전 버전의 후보입니다. 현재 페이지를 다시 확인하세요.")
        self.proposals.decide(proposal, decision)
        if page.confirmed:
            page.confirmed = 0
            page.status = "awaiting_review"
            self.db.commit()
        return self.snapshot(proposal.source_pdf_id)

    def _validated_box(self, page_path: Path, box: dict) -> dict:
        with Image.open(page_path) as image:
            width, height = image.size
        if any(isinstance(box.get(key), bool) or not isinstance(box.get(key), int)
               for key in ("x", "y", "width", "height")):
            raise ValueError("crop 좌표는 정수여야 합니다.")
        x, y, w, h = (box[key] for key in ("x", "y", "width", "height"))
        if x < 0 or y < 0 or w < 20 or h < 20 or x + w > width or y + h > height:
            raise ValueError("crop 영역은 페이지 안에 있어야 하며 최소 20×20픽셀이어야 합니다.")
        return {"x": x, "y": y, "width": w, "height": h}

    def _write_manual_preview(self, page_path: Path, source_id: str, proposal_id: int, box: dict) -> Path:
        directory = storage.DEFAULT_UPLOAD_ROOT / "crop-proposals" / source_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"proposal_{proposal_id}_manual_{uuid4().hex[:8]}.png"
        with Image.open(page_path) as image:
            image.crop((box["x"], box["y"], box["x"] + box["width"],
                        box["y"] + box["height"])).save(path)
        return path

    def edit_proposal(self, proposal_id: int, box: dict) -> dict:
        proposal = self.proposals.get(proposal_id)
        if proposal is None:
            raise LookupError("후보를 찾을 수 없습니다.")
        source = self._source(proposal.source_pdf_id)
        if source.status == "reviewed":
            raise ValueError("확정 후에는 crop을 수정할 수 없습니다.")
        page = self.pages.get(proposal.source_pdf_id, proposal.page_number)
        if page.version != proposal.version:
            raise ValueError("이전 버전의 후보입니다. 현재 페이지를 다시 확인하세요.")
        page_path = self._page_path(proposal.source_pdf_id, proposal.page_number, source.total_pages)
        box = self._validated_box(page_path, box)
        if any(other.id != proposal.id and other.crop_box == box
               for other in self.proposals.list(proposal.source_pdf_id, proposal.page_number, page.version)):
            raise ValueError("같은 영역의 후보가 이미 있습니다.")
        path = self._write_manual_preview(page_path, proposal.source_pdf_id, proposal.id, box)
        proposal.crop_box = box
        proposal.preview_image_path = str(path)
        proposal.origin = "manual"
        proposal.decision = "accepted"
        proposal.decided_at = datetime.now(timezone.utc)
        page.confirmed = 0
        page.status = "awaiting_review"
        self.db.commit()
        return self.snapshot(proposal.source_pdf_id)

    def add_manual_proposal(self, source_id: str, page_number: int, box: dict) -> dict:
        source = self._source(source_id)
        if source.status == "reviewed":
            raise ValueError("확정 후에는 crop을 추가할 수 없습니다.")
        page_path = self._page_path(source_id, page_number, source.total_pages)
        page = self.pages.get(source_id, page_number)
        if page is None:
            raise ValueError("먼저 이 페이지의 후보를 생성하세요.")
        box = self._validated_box(page_path, box)
        if any(other.crop_box == box for other in self.proposals.list(source_id, page_number, page.version)):
            raise ValueError("같은 영역의 후보가 이미 있습니다.")
        proposal = self.proposals.add(
            source_pdf_id=source_id, page_number=page_number, version=page.version,
            crop_box=box, preview_image_path=str(page_path), problem_number=None,
            origin="manual", decision="accepted", decided_at=datetime.now(timezone.utc),
        )
        proposal.preview_image_path = str(self._write_manual_preview(page_path, source_id, proposal.id, box))
        page.confirmed = 0
        page.status = "awaiting_review"
        self.db.commit()
        return self.snapshot(source_id)

    def accept_page(self, source_id: str, page_number: int) -> dict:
        source = self._source(source_id)
        if source.status == "reviewed":
            return self.snapshot(source_id)
        self._page_path(source_id, page_number, source.total_pages)
        page = self.pages.get(source_id, page_number)
        if page is None:
            raise ValueError("먼저 이 페이지의 후보를 생성하세요.")
        self.proposals.accept_pending_page(source_id, page_number, page.version)
        page.confirmed = 1
        page.status = "confirmed"
        self.db.commit()
        return self.snapshot(source_id)

    def confirm(self, source_id: str, page_number: int) -> dict:
        source = self._source(source_id)
        if source.status == "reviewed":
            return self.snapshot(source_id)
        self._page_path(source_id, page_number, source.total_pages)
        page = self.pages.get(source_id, page_number)
        if page is None:
            raise ValueError("먼저 이 페이지의 crop 후보를 생성하세요.")
        if any(p.decision == "pending" for p in self.proposals.list(source_id, page_number, page.version)):
            raise ValueError("이 페이지의 모든 후보를 채택하거나 버려야 합니다.")
        self.pages.confirm(page)
        return self.snapshot(source_id)

    def finalize(self, source_id: str) -> dict:
        source = self._source(source_id)
        if source.status == "reviewed":
            return {"source_pdf_id": source_id, "status": source.status,
                    "imported_problem_count": self.problems.count_by_source_pdf_id(source_id)}
        rows = self.pages.list(source_id)
        if len(rows) != source.total_pages or any(not row.confirmed for row in rows):
            raise ValueError("모든 페이지를 확인한 뒤 확정할 수 있습니다.")
        accepted = [p for row in rows for p in self.proposals.list(source_id, row.page_number, row.version)
                    if p.decision == "accepted"]
        problem_dir = get_problem_storage_dir(source_id)
        for proposal in accepted:
            path = problem_dir / f"P_REVIEW_{proposal.id:06d}.png"
            with Image.open(proposal.preview_image_path) as image:
                image.save(path)
            problem = self.problems.create_from_pdf(
                source_pdf_id=source_id, page_number=proposal.page_number,
                problem_number=proposal.problem_number, elective_subject="unknown",
                problem_image_path=str(path),
                page_image_path=str(self._page_path(source_id, proposal.page_number, source.total_pages)),
                crop_box=proposal.crop_box, status="unclassified", commit=False,
            )
            proposal.problem_id = problem.id
        source.status = "reviewed"
        self.db.commit()
        for proposal in accepted:
            try:
                ProblemOcrApplyService(self.db).apply_ocr_result(proposal.problem_id,
                                                                {"crop_box": proposal.crop_box})
            except Exception:
                # The accepted problem remains imported; region extraction can
                # be retried independently without creating a duplicate row.
                pass
        return {"source_pdf_id": source_id, "status": source.status,
                "imported_problem_count": len(accepted)}

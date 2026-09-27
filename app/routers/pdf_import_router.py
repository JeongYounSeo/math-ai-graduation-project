from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from typing import Literal
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.repositories.problem_repository import ProblemRepository
from app.repositories.source_pdf_repository import SourcePDFRepository
from app.services.pdf_import_service import PDFImportService
from app.services.crop_review_service import CropReviewService

router = APIRouter(prefix="/api/pdf-import", tags=["PDF Import"])


class CropDecision(BaseModel):
    decision: Literal["accepted", "discarded"]


class CropBoxPayload(BaseModel):
    x: int
    y: int
    width: int
    height: int


def _review_call(action):
    try:
        return action()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/review-uploads")
def upload_pdf_for_review(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDF 파일만 업로드할 수 있습니다.")
    return _review_call(lambda: CropReviewService(db).upload(file, file.filename))


@router.get("/source-pdfs/{source_pdf_id}/crop-review")
def get_crop_review(source_pdf_id: str, db: Session = Depends(get_db)):
    return _review_call(lambda: CropReviewService(db).snapshot(source_pdf_id))


@router.post("/source-pdfs/{source_pdf_id}/crop-review/pages/{page_number}/prepare")
def prepare_crop_page(source_pdf_id: str, page_number: int, db: Session = Depends(get_db)):
    return _review_call(lambda: CropReviewService(db).prepare(source_pdf_id, page_number))


@router.post("/source-pdfs/{source_pdf_id}/crop-review/pages/{page_number}/retry")
def retry_crop_page(source_pdf_id: str, page_number: int, db: Session = Depends(get_db)):
    return _review_call(lambda: CropReviewService(db).prepare(source_pdf_id, page_number, retry=True))


@router.patch("/crop-proposals/{proposal_id}")
def decide_crop_proposal(proposal_id: int, payload: CropDecision, db: Session = Depends(get_db)):
    return _review_call(lambda: CropReviewService(db).decide(proposal_id, payload.decision))


@router.patch("/crop-proposals/{proposal_id}/box")
def edit_crop_proposal(proposal_id: int, payload: CropBoxPayload, db: Session = Depends(get_db)):
    return _review_call(lambda: CropReviewService(db).edit_proposal(proposal_id, payload.model_dump()))


@router.post("/source-pdfs/{source_pdf_id}/crop-review/pages/{page_number}/proposals")
def add_crop_proposal(source_pdf_id: str, page_number: int, payload: CropBoxPayload,
                      db: Session = Depends(get_db)):
    return _review_call(lambda: CropReviewService(db).add_manual_proposal(
        source_pdf_id, page_number, payload.model_dump()))


@router.post("/source-pdfs/{source_pdf_id}/crop-review/pages/{page_number}/accept-all")
def accept_page_crop_proposals(source_pdf_id: str, page_number: int, db: Session = Depends(get_db)):
    return _review_call(lambda: CropReviewService(db).accept_page(source_pdf_id, page_number))


@router.post("/source-pdfs/{source_pdf_id}/crop-review/pages/{page_number}/confirm")
def confirm_crop_page(source_pdf_id: str, page_number: int, db: Session = Depends(get_db)):
    return _review_call(lambda: CropReviewService(db).confirm(source_pdf_id, page_number))


@router.post("/source-pdfs/{source_pdf_id}/crop-review/finalize")
def finalize_crop_review(source_pdf_id: str, db: Session = Depends(get_db)):
    return _review_call(lambda: CropReviewService(db).finalize(source_pdf_id))


@router.post("/upload")
async def upload_pdf(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDF 파일만 업로드할 수 있습니다.")

    service = PDFImportService(db)
    result = service.import_pdf(file, file.filename)
    return result


@router.get("/source-pdfs")
async def list_source_pdfs(db: Session = Depends(get_db)):
    repo = SourcePDFRepository(db)
    return repo.get_all()


@router.get("/source-pdfs/{source_pdf_id}/problems")
async def get_source_pdf_problems(source_pdf_id: str, db: Session = Depends(get_db)):
    repo = ProblemRepository(db)
    problems = await repo.get_by_source_pdf_id(source_pdf_id)
    return problems


@router.post("/source-pdfs/{source_pdf_id}/reprocess")
def reprocess_source_pdf(
    source_pdf_id: str, crop_mode: Literal["a_only", "auto"] = "a_only",
    db: Session = Depends(get_db),
):
    """Reprocess into a new source dataset, optionally reviewing pages with Gemini."""
    try:
        return PDFImportService(db).reprocess_source_pdf(source_pdf_id, crop_mode=crop_mode)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.repositories.problem_repository import ProblemRepository
from app.repositories.source_pdf_repository import SourcePDFRepository
from app.services.pdf_import_service import PDFImportService

router = APIRouter(prefix="/api/pdf-import", tags=["PDF Import"])


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
    problems = repo.get_by_source_pdf_id(source_pdf_id)
    return problems

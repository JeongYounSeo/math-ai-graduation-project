from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class SourcePDFBase(BaseModel):
    source_pdf_id: str
    original_filename: str
    stored_filename: str
    file_path: str
    total_pages: int = 0
    exam_name: Optional[str] = None
    year: Optional[int] = None
    month: Optional[int] = None
    grade: Optional[str] = None
    subject: Optional[str] = None
    status: str = "uploaded"


class SourcePDFCreate(SourcePDFBase):
    pass


class SourcePDF(SourcePDFBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

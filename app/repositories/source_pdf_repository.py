from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.source_pdf import SourcePDF


class SourcePDFRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, payload: dict) -> SourcePDF:
        source_pdf = SourcePDF(**payload)
        self.db.add(source_pdf)
        self.db.commit()
        self.db.refresh(source_pdf)
        return source_pdf

    def get_all(self) -> List[SourcePDF]:
        return self.db.query(SourcePDF).order_by(SourcePDF.created_at.desc()).all()

    def get_by_id(self, source_pdf_id: str) -> Optional[SourcePDF]:
        return self.db.query(SourcePDF).filter(SourcePDF.source_pdf_id == source_pdf_id).first()

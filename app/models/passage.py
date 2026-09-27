from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, ForeignKey
from sqlalchemy.sql import func
from app.core.database import Base


class Passage(Base):
    __tablename__ = "passages"

    id = Column(Integer, primary_key=True, index=True)
    source_pdf_id = Column(Integer, ForeignKey("source_pdfs.id"), nullable=False, index=True)
    page_number = Column(Integer, nullable=False)
    passage_image_path = Column(String, nullable=False)
    crop_box = Column(JSON, nullable=True)
    ocr_text = Column(Text, nullable=True)
    latex_text = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

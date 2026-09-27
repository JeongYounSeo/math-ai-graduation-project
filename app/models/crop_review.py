from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.core.database import Base


class CropPageReview(Base):
    __tablename__ = "crop_page_reviews"
    __table_args__ = (UniqueConstraint("source_pdf_id", "page_number"),)

    id = Column(Integer, primary_key=True)
    source_pdf_id = Column(String, ForeignKey("source_pdfs.source_pdf_id"), nullable=False, index=True)
    page_number = Column(Integer, nullable=False)
    version = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default="unprepared")
    confirmed = Column(Integer, nullable=False, default=0)
    method = Column(String, nullable=True)
    verdict = Column(String, nullable=True)
    reason = Column(Text, nullable=True)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())


class CropProposal(Base):
    __tablename__ = "crop_proposals"

    id = Column(Integer, primary_key=True)
    source_pdf_id = Column(String, ForeignKey("source_pdfs.source_pdf_id"), nullable=False, index=True)
    page_number = Column(Integer, nullable=False)
    version = Column(Integer, nullable=False)
    crop_box = Column(JSON, nullable=False)
    preview_image_path = Column(String, nullable=False)
    problem_number = Column(Integer, nullable=True)
    origin = Column(String, nullable=False)
    decision = Column(String, nullable=False, default="pending")
    decided_at = Column(DateTime(timezone=True), nullable=True)
    problem_id = Column(Integer, ForeignKey("problems.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

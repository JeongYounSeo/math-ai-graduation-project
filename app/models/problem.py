from sqlalchemy import Column, Integer, String, Text, DateTime, JSON
from sqlalchemy.sql import func
from app.core.database import Base
import enum
from pathlib import Path


class ProblemStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    EXTRACTED = "extracted"
    ANALYZED = "analyzed"
    CLASSIFIED = "classified"
    VERIFIED = "verified"
    UNCLASSIFIED = "unclassified"
    REVIEWED = "reviewed"
    EXCLUDED = "excluded"


class Problem(Base):
    __tablename__ = "problems"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False, default="")
    source_type = Column(String, nullable=False, default="pdf")
    source_name = Column(String)
    raw_text = Column(Text)
    raw_ocr_text = Column(Text)
    latex_text = Column(Text)
    extracted_conditions = Column(JSON)  # JSON 객체
    large_unit = Column(String)  # 수학 I, 수학 II 등
    middle_unit = Column(String)  # 세부 단원
    difficulty_level = Column(String)
    difficulty = Column(String)
    score = Column(Integer)
    answer = Column(String)
    solution_text = Column(Text)
    detected_module_ids = Column(JSON)  # JSON 리스트
    small_type_ids = Column(JSON)
    tags = Column(JSON)
    memo = Column(Text)
    source_pdf_id = Column(String, nullable=True, index=True)
    page_number = Column(Integer, nullable=True)
    problem_number = Column(Integer, nullable=True)
    elective_subject = Column(String, nullable=True)
    problem_image_path = Column(String, nullable=True)
    page_image_path = Column(String, nullable=True)
    crop_box = Column(JSON, default={})
    original_candidate_boxes = Column(JSON, nullable=True)
    status = Column(String, default=ProblemStatus.UNCLASSIFIED.value)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    @property
    def problem_image_url(self) -> str | None:
        if not self.problem_image_path:
            return None
        path = Path(self.problem_image_path)
        if path.is_absolute():
            try:
                relative = path.relative_to(Path("uploads"))
                return f"/uploads/{relative.as_posix()}"
            except ValueError:
                return f"/uploads/{path.name}"
        return self.problem_image_path

    @property
    def page_image_url(self) -> str | None:
        if not self.page_image_path:
            return None
        path = Path(self.page_image_path)
        if path.is_absolute():
            try:
                relative = path.relative_to(Path("uploads"))
                return f"/uploads/{relative.as_posix()}"
            except ValueError:
                return f"/uploads/{path.name}"
        return self.page_image_path
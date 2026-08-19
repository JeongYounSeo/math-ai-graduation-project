from sqlalchemy import Column, Integer, String, Text, DateTime, JSON
from sqlalchemy.sql import func
from app.core.database import Base
import enum
from pathlib import Path


def _to_uploads_url(image_path: str | None) -> str | None:
    """저장된 이미지 경로(절대/상대, '\\' 또는 '/' 구분자 무관)를 /uploads/... URL로 변환한다.

    PDF import는 uploads 루트 기준 상대 경로(Windows에서는 '\\' 포함)를 저장하는데,
    기존 구현은 절대 경로만 변환하고 상대 경로는 그대로 반환해 브라우저가 못 읽는
    URL(백슬래시 포함, 앞에 '/' 없음)이 나가는 문제가 있었다.
    """
    if not image_path:
        return None
    normalized = image_path.replace("\\", "/")
    marker = "uploads/"
    idx = normalized.find(marker)
    if idx >= 0:
        return "/" + normalized[idx:]
    return f"/uploads/{Path(normalized).name}"


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
        return _to_uploads_url(self.problem_image_path)

    @property
    def page_image_url(self) -> str | None:
        return _to_uploads_url(self.page_image_path)

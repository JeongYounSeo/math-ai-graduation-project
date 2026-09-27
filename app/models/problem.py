from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, ForeignKey
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
    FAILED = "failed"


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
    # 객관식 보기 텍스트를 Problem 레코드에 비정규화로 함께 저장(설계 §5-1).
    # 정규화된 정본은 ProblemChoice 테이블이며, 이 컬럼은 조회 편의용 사본이다.
    # apply_ocr_result 가 ProblemChoice replace 시 이 컬럼도 동시 갱신한다.
    answer_type = Column(String, nullable=True)  # 예: "multiple_choice"
    choices = Column(JSON, nullable=True)  # list[str] 보기 텍스트 (정답 정보 없음)
    detected_module_ids = Column(JSON)  # JSON 리스트
    small_type_ids = Column(JSON)
    tags = Column(JSON)
    memo = Column(Text)
    source_pdf_id = Column(String, nullable=True, index=True)
    passage_id = Column(Integer, ForeignKey("passages.id"), nullable=True, index=True)
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
        import app.core.storage as storage
        path = Path(self.problem_image_path)
        try:
            relative = path.resolve().relative_to(storage.DEFAULT_UPLOAD_ROOT.resolve())
            return f"/uploads/{relative.as_posix()}"
        except ValueError:
            return None

    @property
    def page_image_url(self) -> str | None:
        if not self.page_image_path:
            return None
        import app.core.storage as storage
        path = Path(self.page_image_path)
        try:
            relative = path.resolve().relative_to(storage.DEFAULT_UPLOAD_ROOT.resolve())
            return f"/uploads/{relative.as_posix()}"
        except ValueError:
            return None

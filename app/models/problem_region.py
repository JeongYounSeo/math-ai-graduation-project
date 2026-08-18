from sqlalchemy import Column, Integer, String, Text, Float, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


# 지원하는 region_type 값 (DB level enum은 사용하지 않고 문자열로 저장한다)
REGION_TYPES = [
    "full_problem",
    "question_body",
    "condition_box",
    "figure",
    "graph",
    "table",
    "choice_group",
    "choice_option",
    "formula",
    "passage",
    "unknown",
]


class ProblemRegion(Base):
    """문제 이미지 안의 의미 영역(전체 문제, 본문, 그림, 보기 등)을 저장한다.

    프로젝트 관례상 DB-level ForeignKey()는 사용하지 않고,
    problem_id / parent_region_id는 plain integer column으로 관계를 표현한다.
    """

    __tablename__ = "problem_regions"

    id = Column(Integer, primary_key=True, index=True)
    problem_id = Column(Integer, nullable=False, index=True)
    parent_region_id = Column(Integer, nullable=True)
    region_type = Column(String, nullable=False, index=True)
    label = Column(String, nullable=True)
    order_index = Column(Integer, default=0)
    page_number = Column(Integer, nullable=True)

    # 좌표 정보
    x1 = Column(Float, nullable=True)
    y1 = Column(Float, nullable=True)
    x2 = Column(Float, nullable=True)
    y2 = Column(Float, nullable=True)
    page_width = Column(Float, nullable=True)
    page_height = Column(Float, nullable=True)

    # 이미지 경로
    image_path = Column(String, nullable=True)
    cropped_image_path = Column(String, nullable=True)

    # 텍스트 정보
    extracted_text = Column(Text, nullable=True)
    latex_text = Column(Text, nullable=True)
    normalized_text = Column(Text, nullable=True)

    # 메타 정보
    confidence = Column(Float, nullable=True)
    provider = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

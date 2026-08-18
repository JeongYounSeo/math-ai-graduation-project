from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, Enum, ForeignKey
from sqlalchemy.sql import func
from app.core.database import Base
import enum

class GeneratedProblemStatus(str, enum.Enum):
    DRAFT = "draft"
    VERIFIED = "verified"
    REJECTED = "rejected"

class GeneratedProblem(Base):
    __tablename__ = "generated_problems"

    id = Column(Integer, primary_key=True, index=True)
    generated_problem_id = Column(String, unique=True, nullable=False, index=True)
    source_problem_id = Column(Integer, ForeignKey("problems.id"))
    used_module_ids = Column(JSON)  # JSON 리스트
    used_combination_id = Column(String)
    problem_text = Column(Text)
    problem_latex = Column(Text)
    answer = Column(String)
    solution_text = Column(Text)
    verification_result = Column(JSON)  # JSON 객체
    status = Column(Enum(GeneratedProblemStatus), default=GeneratedProblemStatus.DRAFT)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
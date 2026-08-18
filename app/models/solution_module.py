from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, Enum
from sqlalchemy.sql import func
from app.core.database import Base
import enum

class SolutionModuleStatus(str, enum.Enum):
    DRAFT = "draft"
    VERIFIED = "verified"
    DEPRECATED = "deprecated"

class SolutionModule(Base):
    __tablename__ = "solution_modules"

    id = Column(Integer, primary_key=True, index=True)
    module_id = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    large_unit = Column(String)
    middle_unit = Column(String)
    description = Column(Text)
    trigger_conditions = Column(JSON)  # JSON 리스트
    core_concepts = Column(JSON)  # JSON 리스트
    core_relations = Column(JSON)  # JSON 리스트
    input_variables = Column(JSON)  # JSON 리스트
    output_targets = Column(JSON)  # JSON 리스트
    known_unknown_patterns = Column(JSON)  # JSON 리스트
    solution_steps = Column(JSON)  # JSON 리스트
    common_mistakes = Column(JSON)  # JSON 리스트
    difficulty_factors = Column(JSON)  # JSON 리스트
    can_combine_with = Column(JSON)  # JSON 리스트
    generation_rules = Column(JSON)  # JSON 객체
    example_problem_ids = Column(JSON)  # JSON 리스트
    status = Column(Enum(SolutionModuleStatus), default=SolutionModuleStatus.DRAFT)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
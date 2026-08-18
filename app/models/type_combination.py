from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, Enum
from sqlalchemy.sql import func
from app.core.database import Base
import enum

class TypeCombinationStatus(str, enum.Enum):
    DRAFT = "draft"
    VERIFIED = "verified"
    DEPRECATED = "deprecated"

class TypeCombination(Base):
    __tablename__ = "type_combinations"

    id = Column(Integer, primary_key=True, index=True)
    combination_id = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    module_sequence = Column(JSON)  # JSON 리스트
    connection_rule = Column(Text)
    target_problem_types = Column(JSON)  # JSON 리스트
    required_conditions = Column(JSON)  # JSON 리스트
    generation_strategy = Column(Text)
    difficulty_level = Column(String)
    example_problem_ids = Column(JSON)  # JSON 리스트
    status = Column(Enum(TypeCombinationStatus), default=TypeCombinationStatus.DRAFT)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
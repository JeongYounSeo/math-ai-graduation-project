from sqlalchemy import Column, Integer, String, Text, DateTime, JSON
from sqlalchemy.sql import func
from app.core.database import Base

class ConceptModule(Base):
    __tablename__ = "concept_modules"

    id = Column(Integer, primary_key=True, index=True)
    concept_id = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    large_unit = Column(String)
    middle_unit = Column(String)
    description = Column(Text)
    formula_latex = Column(Text)
    variables = Column(JSON)  # JSON 리스트
    relation_structure = Column(JSON)  # JSON 객체
    examples = Column(JSON)  # JSON 리스트
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
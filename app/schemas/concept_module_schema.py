from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime

class ConceptModuleBase(BaseModel):
    concept_id: str
    name: str
    large_unit: Optional[str] = None
    middle_unit: Optional[str] = None
    description: Optional[str] = None
    formula_latex: Optional[str] = None
    variables: Optional[List[str]] = None
    relation_structure: Optional[Dict[str, Any]] = None
    examples: Optional[List[Dict[str, Any]]] = None

class ConceptModuleCreate(ConceptModuleBase):
    pass

class ConceptModuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    formula_latex: Optional[str] = None
    variables: Optional[List[str]] = None
    relation_structure: Optional[Dict[str, Any]] = None
    examples: Optional[List[Dict[str, Any]]] = None

class ConceptModule(ConceptModuleBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
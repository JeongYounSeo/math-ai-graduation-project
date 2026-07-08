from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.models.type_combination import TypeCombinationStatus

class TypeCombinationBase(BaseModel):
    combination_id: str
    name: str
    module_sequence: Optional[List[str]] = None
    connection_rule: Optional[str] = None
    target_problem_types: Optional[List[str]] = None
    required_conditions: Optional[List[str]] = None
    generation_strategy: Optional[str] = None
    difficulty_level: Optional[str] = None
    example_problem_ids: Optional[List[int]] = None
    status: TypeCombinationStatus = TypeCombinationStatus.DRAFT

class TypeCombinationCreate(TypeCombinationBase):
    pass

class TypeCombinationUpdate(BaseModel):
    name: Optional[str] = None
    module_sequence: Optional[List[str]] = None
    connection_rule: Optional[str] = None
    target_problem_types: Optional[List[str]] = None
    required_conditions: Optional[List[str]] = None
    generation_strategy: Optional[str] = None
    difficulty_level: Optional[str] = None
    example_problem_ids: Optional[List[int]] = None
    status: Optional[TypeCombinationStatus] = None

class TypeCombination(TypeCombinationBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
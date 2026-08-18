from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.models.solution_module import SolutionModuleStatus

class SolutionModuleBase(BaseModel):
    module_id: str
    name: str
    large_unit: Optional[str] = None
    middle_unit: Optional[str] = None
    description: Optional[str] = None
    trigger_conditions: Optional[List[str]] = None
    core_concepts: Optional[List[str]] = None
    core_relations: Optional[List[Dict[str, Any]]] = None
    input_variables: Optional[List[str]] = None
    output_targets: Optional[List[str]] = None
    known_unknown_patterns: Optional[List[Dict[str, Any]]] = None
    solution_steps: Optional[List[str]] = None
    common_mistakes: Optional[List[str]] = None
    difficulty_factors: Optional[List[str]] = None
    can_combine_with: Optional[List[str]] = None
    generation_rules: Optional[Dict[str, Any]] = None
    example_problem_ids: Optional[List[int]] = None
    status: SolutionModuleStatus = SolutionModuleStatus.DRAFT

class SolutionModuleCreate(SolutionModuleBase):
    pass

class SolutionModuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    trigger_conditions: Optional[List[str]] = None
    core_concepts: Optional[List[str]] = None
    core_relations: Optional[List[Dict[str, Any]]] = None
    input_variables: Optional[List[str]] = None
    output_targets: Optional[List[str]] = None
    known_unknown_patterns: Optional[List[Dict[str, Any]]] = None
    solution_steps: Optional[List[str]] = None
    common_mistakes: Optional[List[str]] = None
    difficulty_factors: Optional[List[str]] = None
    can_combine_with: Optional[List[str]] = None
    generation_rules: Optional[Dict[str, Any]] = None
    example_problem_ids: Optional[List[int]] = None
    status: Optional[SolutionModuleStatus] = None

class SolutionModule(SolutionModuleBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
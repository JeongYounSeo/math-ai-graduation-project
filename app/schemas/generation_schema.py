from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.models.generated_problem import GeneratedProblemStatus

class GenerationRequest(BaseModel):
    selected_module_ids: List[str]
    selected_combination_id: Optional[str] = None
    difficulty_level: Optional[str] = "medium"
    generation_goal: str

class GenerationResponse(BaseModel):
    generated_problem_id: str
    prompt_used: str
    mock_problem: Dict[str, Any]
    status: str = "draft"

class GeneratedProblemBase(BaseModel):
    generated_problem_id: str
    source_problem_id: Optional[int] = None
    used_module_ids: Optional[List[str]] = None
    used_combination_id: Optional[str] = None
    problem_text: Optional[str] = None
    problem_latex: Optional[str] = None
    answer: Optional[str] = None
    solution_text: Optional[str] = None
    verification_result: Optional[Dict[str, Any]] = None
    status: GeneratedProblemStatus = GeneratedProblemStatus.DRAFT

class GeneratedProblem(GeneratedProblemBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
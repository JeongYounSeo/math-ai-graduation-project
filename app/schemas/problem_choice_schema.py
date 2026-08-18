from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class ProblemChoiceBase(BaseModel):
    problem_id: int
    region_id: Optional[int] = None
    choice_index: int
    choice_label: Optional[str] = None
    text: Optional[str] = None
    latex_text: Optional[str] = None
    normalized_text: Optional[str] = None
    is_correct: Optional[bool] = None
    is_distractor: Optional[bool] = None


class ProblemChoiceCreate(ProblemChoiceBase):
    pass


class ProblemChoiceUpdate(BaseModel):
    region_id: Optional[int] = None
    choice_index: Optional[int] = None
    choice_label: Optional[str] = None
    text: Optional[str] = None
    latex_text: Optional[str] = None
    normalized_text: Optional[str] = None
    is_correct: Optional[bool] = None
    is_distractor: Optional[bool] = None


class ProblemChoice(ProblemChoiceBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ProblemChoiceReplaceRequest(BaseModel):
    choices: List[str]

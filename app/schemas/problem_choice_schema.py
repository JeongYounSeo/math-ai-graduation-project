from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class ProblemChoiceSchema(BaseModel):
    """ProblemChoice 응답용 스키마."""

    id: int
    problem_id: int
    region_id: Optional[int] = None
    choice_index: int
    choice_label: Optional[str] = None
    text: Optional[str] = None
    latex_text: Optional[str] = None
    normalized_text: Optional[str] = None
    is_correct: Optional[bool] = None
    is_distractor: Optional[bool] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ProblemChoiceCreate(BaseModel):
    """단일 ProblemChoice 생성 입력용 스키마."""

    choice_index: int
    choice_label: Optional[str] = None
    text: Optional[str] = None
    latex_text: Optional[str] = None
    normalized_text: Optional[str] = None
    region_id: Optional[int] = None
    is_correct: Optional[bool] = None
    is_distractor: Optional[bool] = None


class ProblemChoiceUpdate(BaseModel):
    """ProblemChoice PATCH 입력용 스키마(모든 필드 Optional)."""

    choice_index: Optional[int] = None
    choice_label: Optional[str] = None
    text: Optional[str] = None
    latex_text: Optional[str] = None
    normalized_text: Optional[str] = None
    region_id: Optional[int] = None
    is_correct: Optional[bool] = None
    is_distractor: Optional[bool] = None


class ProblemChoiceReplaceRequest(BaseModel):
    """POST replace 엔드포인트 입력용 스키마."""

    choices: List[str]


class ProblemChoicesResponse(BaseModel):
    """문제 단위 보기 목록 응답용 스키마."""

    problem_id: int
    choices: List[ProblemChoiceSchema] = []

    class Config:
        from_attributes = True

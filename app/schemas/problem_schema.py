from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.models.problem import ProblemStatus


class ProblemBase(BaseModel):
    title: str = ""
    source_type: str = "pdf"
    source_name: Optional[str] = None
    raw_text: Optional[str] = None
    raw_ocr_text: Optional[str] = None
    latex_text: Optional[str] = None
    extracted_conditions: Optional[Dict[str, Any]] = None
    large_unit: Optional[str] = None
    middle_unit: Optional[str] = None
    difficulty_level: Optional[str] = None
    difficulty: Optional[str] = None
    score: Optional[int] = None
    answer: Optional[str] = None
    solution_text: Optional[str] = None
    detected_module_ids: Optional[List[str]] = None
    small_type_ids: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    memo: Optional[str] = None
    source_pdf_id: Optional[str] = None
    page_number: Optional[int] = None
    problem_number: Optional[int] = None
    elective_subject: Optional[str] = None
    problem_image_path: Optional[str] = None
    page_image_path: Optional[str] = None
    crop_box: Optional[Dict[str, Any]] = None
    status: str = ProblemStatus.UNCLASSIFIED.value


class ProblemCreate(ProblemBase):
    pass


class ProblemUpdate(BaseModel):
    title: Optional[str] = None
    raw_text: Optional[str] = None
    raw_ocr_text: Optional[str] = None
    latex_text: Optional[str] = None
    extracted_conditions: Optional[Dict[str, Any]] = None
    large_unit: Optional[str] = None
    middle_unit: Optional[str] = None
    difficulty_level: Optional[str] = None
    difficulty: Optional[str] = None
    score: Optional[int] = None
    answer: Optional[str] = None
    solution_text: Optional[str] = None
    detected_module_ids: Optional[List[str]] = None
    small_type_ids: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    memo: Optional[str] = None
    source_pdf_id: Optional[str] = None
    page_number: Optional[int] = None
    problem_number: Optional[int] = None
    elective_subject: Optional[str] = None
    problem_image_path: Optional[str] = None
    page_image_path: Optional[str] = None
    crop_box: Optional[Dict[str, Any]] = None
    status: Optional[str] = None


class Problem(ProblemBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    problem_image_url: Optional[str] = None
    page_image_url: Optional[str] = None

    class Config:
        from_attributes = True
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class ProblemRegionBase(BaseModel):
    problem_id: int
    parent_region_id: Optional[int] = None
    region_type: str
    label: Optional[str] = None
    order_index: int = 0
    page_number: Optional[int] = None

    x1: Optional[float] = None
    y1: Optional[float] = None
    x2: Optional[float] = None
    y2: Optional[float] = None
    page_width: Optional[float] = None
    page_height: Optional[float] = None

    image_path: Optional[str] = None
    cropped_image_path: Optional[str] = None

    extracted_text: Optional[str] = None
    latex_text: Optional[str] = None
    normalized_text: Optional[str] = None

    confidence: Optional[float] = None
    provider: Optional[str] = None


class ProblemRegionCreate(ProblemRegionBase):
    pass


class ProblemRegionUpdate(BaseModel):
    parent_region_id: Optional[int] = None
    region_type: Optional[str] = None
    label: Optional[str] = None
    order_index: Optional[int] = None
    page_number: Optional[int] = None

    x1: Optional[float] = None
    y1: Optional[float] = None
    x2: Optional[float] = None
    y2: Optional[float] = None
    page_width: Optional[float] = None
    page_height: Optional[float] = None

    image_path: Optional[str] = None
    cropped_image_path: Optional[str] = None

    extracted_text: Optional[str] = None
    latex_text: Optional[str] = None
    normalized_text: Optional[str] = None

    confidence: Optional[float] = None
    provider: Optional[str] = None


class ProblemRegion(ProblemRegionBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

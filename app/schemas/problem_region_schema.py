from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


class ProblemRegionItemSchema(BaseModel):
    id: int
    region_id: int
    label: str
    order_index: int
    text: Optional[str] = None
    latex: Optional[str] = None
    image_path: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ProblemRegionSchema(BaseModel):
    id: int
    problem_id: int
    region_type: str
    order_index: int
    image_path: Optional[str] = None
    bounding_box: Optional[Dict[str, Any]] = None
    ocr_text: Optional[str] = None
    latex_text: Optional[str] = None
    confidence: Optional[float] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    items: List[ProblemRegionItemSchema] = []

    class Config:
        from_attributes = True


class PassageSchema(BaseModel):
    id: int
    source_pdf_id: int
    page_number: int
    passage_image_path: str
    crop_box: Optional[Dict[str, Any]] = None
    ocr_text: Optional[str] = None
    latex_text: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ProblemRegionsResponse(BaseModel):
    problem_id: int
    regions: List[ProblemRegionSchema] = []

    class Config:
        from_attributes = True

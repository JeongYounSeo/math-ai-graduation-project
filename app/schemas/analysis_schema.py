from pydantic import BaseModel
from typing import Optional, List, Dict, Any

class AnalysisRequest(BaseModel):
    problem_text: str

class AnalysisResponse(BaseModel):
    prompt_used: str
    mock_analysis: Dict[str, Any]
    extracted_conditions: Dict[str, Any]
    large_unit: str
    middle_unit: str
    detected_module_ids: List[str]
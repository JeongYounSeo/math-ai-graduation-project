import json
from typing import Any, Dict

def safe_json_loads(json_str: str) -> Dict[str, Any]:
    """안전한 JSON 파싱"""
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return {}

def safe_json_dumps(data: Any) -> str:
    """안전한 JSON 직렬화"""
    try:
        return json.dumps(data, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return "{}"
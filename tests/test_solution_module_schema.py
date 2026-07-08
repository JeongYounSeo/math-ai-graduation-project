import pytest
from app.schemas.solution_module_schema import SolutionModuleCreate, SolutionModuleStatus

def test_solution_module_create():
    """SolutionModule 생성 스키마 테스트"""
    data = {
        "module_id": "TEST_MODULE",
        "name": "테스트 모듈",
        "description": "테스트용 소유형 모듈",
        "trigger_conditions": ["조건1", "조건2"],
        "core_concepts": ["개념1"],
        "status": SolutionModuleStatus.DRAFT
    }
    
    schema = SolutionModuleCreate(**data)
    assert schema.module_id == "TEST_MODULE"
    assert schema.name == "테스트 모듈"
    assert len(schema.trigger_conditions) == 2

def test_solution_module_status_enum():
    """SolutionModule 상태 enum 테스트"""
    assert SolutionModuleStatus.DRAFT == "draft"
    assert SolutionModuleStatus.VERIFIED == "verified"
    assert SolutionModuleStatus.DEPRECATED == "deprecated"
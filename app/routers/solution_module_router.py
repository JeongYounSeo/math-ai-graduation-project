from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from app.core.database import get_db
from app.schemas.solution_module_schema import SolutionModule, SolutionModuleCreate, SolutionModuleUpdate
from app.repositories.solution_module_repository import SolutionModuleRepository
from app.services.solution_module_service import SolutionModuleService
from app.services.prompt_builder_service import PromptBuilderService

router = APIRouter()

@router.post("/", response_model=Dict[str, Any])
async def create_solution_module_from_description(
    user_description: str,
    db: Session = Depends(get_db)
):
    prompt_builder = PromptBuilderService()
    service = SolutionModuleService(prompt_builder)
    result = await service.create_module_from_description(user_description)
    
    # 실제로는 draft 상태로 저장
    repo = SolutionModuleRepository(db)
    module_data = SolutionModuleCreate(**result["mock_module"])
    created_module = await repo.create(module_data)
    
    return {
        "module": SolutionModule.from_orm(created_module),
        "prompt_used": result["prompt_used"]
    }

@router.get("/", response_model=List[SolutionModule])
async def get_solution_modules(db: Session = Depends(get_db)):
    repo = SolutionModuleRepository(db)
    return await repo.get_all()

@router.get("/{module_id}", response_model=SolutionModule)
async def get_solution_module(
    module_id: str,
    db: Session = Depends(get_db)
):
    repo = SolutionModuleRepository(db)
    module = await repo.get_by_module_id(module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Solution module not found")
    return module

@router.patch("/{module_id}/verify")
async def verify_solution_module(
    module_id: str,
    db: Session = Depends(get_db)
):
    repo = SolutionModuleRepository(db)
    module = await repo.get_by_module_id(module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Solution module not found")
    
    update_data = SolutionModuleUpdate(status="verified")
    updated_module = await repo.update(module.id, update_data)
    return {"message": "Module verified", "module": SolutionModule.from_orm(updated_module)}
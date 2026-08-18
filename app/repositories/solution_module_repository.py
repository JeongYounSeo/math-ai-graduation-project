from sqlalchemy.orm import Session
from typing import List, Optional
from app.models.solution_module import SolutionModule
from app.schemas.solution_module_schema import SolutionModuleCreate, SolutionModuleUpdate

class SolutionModuleRepository:
    def __init__(self, db: Session):
        self.db = db

    async def create(self, module: SolutionModuleCreate) -> SolutionModule:
        db_module = SolutionModule(**module.model_dump())
        self.db.add(db_module)
        self.db.commit()
        self.db.refresh(db_module)
        return db_module

    async def get_by_id(self, module_id: int) -> Optional[SolutionModule]:
        return self.db.query(SolutionModule).filter(SolutionModule.id == module_id).first()

    async def get_by_module_id(self, module_id: str) -> Optional[SolutionModule]:
        return self.db.query(SolutionModule).filter(SolutionModule.module_id == module_id).first()

    async def get_all(self) -> List[SolutionModule]:
        return self.db.query(SolutionModule).all()

    async def update(self, module_id: int, module_update: SolutionModuleUpdate) -> Optional[SolutionModule]:
        db_module = self.db.query(SolutionModule).filter(SolutionModule.id == module_id).first()
        if db_module:
            for key, value in module_update.model_dump(exclude_unset=True).items():
                setattr(db_module, key, value)
            self.db.commit()
            self.db.refresh(db_module)
        return db_module

    async def delete(self, module_id: int) -> bool:
        db_module = self.db.query(SolutionModule).filter(SolutionModule.id == module_id).first()
        if db_module:
            self.db.delete(db_module)
            self.db.commit()
            return True
        return False
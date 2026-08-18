from sqlalchemy.orm import Session
from typing import List, Optional
from app.models.concept_module import ConceptModule
from app.schemas.concept_module_schema import ConceptModuleCreate, ConceptModuleUpdate

class ConceptModuleRepository:
    def __init__(self, db: Session):
        self.db = db

    async def create(self, concept: ConceptModuleCreate) -> ConceptModule:
        db_concept = ConceptModule(**concept.model_dump())
        self.db.add(db_concept)
        self.db.commit()
        self.db.refresh(db_concept)
        return db_concept

    async def get_by_id(self, concept_id: int) -> Optional[ConceptModule]:
        return self.db.query(ConceptModule).filter(ConceptModule.id == concept_id).first()

    async def get_by_concept_id(self, concept_id: str) -> Optional[ConceptModule]:
        return self.db.query(ConceptModule).filter(ConceptModule.concept_id == concept_id).first()

    async def get_all(self) -> List[ConceptModule]:
        return self.db.query(ConceptModule).all()

    async def update(self, concept_id: int, concept_update: ConceptModuleUpdate) -> Optional[ConceptModule]:
        db_concept = self.db.query(ConceptModule).filter(ConceptModule.id == concept_id).first()
        if db_concept:
            for key, value in concept_update.model_dump(exclude_unset=True).items():
                setattr(db_concept, key, value)
            self.db.commit()
            self.db.refresh(db_concept)
        return db_concept

    async def delete(self, concept_id: int) -> bool:
        db_concept = self.db.query(ConceptModule).filter(ConceptModule.id == concept_id).first()
        if db_concept:
            self.db.delete(db_concept)
            self.db.commit()
            return True
        return False
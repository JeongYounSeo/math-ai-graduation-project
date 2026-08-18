from sqlalchemy.orm import Session
from typing import List, Optional
from app.models.type_combination import TypeCombination
from app.schemas.type_combination_schema import TypeCombinationCreate, TypeCombinationUpdate

class TypeCombinationRepository:
    def __init__(self, db: Session):
        self.db = db

    async def create(self, combination: TypeCombinationCreate) -> TypeCombination:
        db_combination = TypeCombination(**combination.model_dump())
        self.db.add(db_combination)
        self.db.commit()
        self.db.refresh(db_combination)
        return db_combination

    async def get_by_id(self, combination_id: int) -> Optional[TypeCombination]:
        return self.db.query(TypeCombination).filter(TypeCombination.id == combination_id).first()

    async def get_by_combination_id(self, combination_id: str) -> Optional[TypeCombination]:
        return self.db.query(TypeCombination).filter(TypeCombination.combination_id == combination_id).first()

    async def get_all(self) -> List[TypeCombination]:
        return self.db.query(TypeCombination).all()

    async def update(self, combination_id: int, combination_update: TypeCombinationUpdate) -> Optional[TypeCombination]:
        db_combination = self.db.query(TypeCombination).filter(TypeCombination.id == combination_id).first()
        if db_combination:
            for key, value in combination_update.model_dump(exclude_unset=True).items():
                setattr(db_combination, key, value)
            self.db.commit()
            self.db.refresh(db_combination)
        return db_combination

    async def delete(self, combination_id: int) -> bool:
        db_combination = self.db.query(TypeCombination).filter(TypeCombination.id == combination_id).first()
        if db_combination:
            self.db.delete(db_combination)
            self.db.commit()
            return True
        return False
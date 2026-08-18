from sqlalchemy.orm import Session
from typing import List, Optional
from app.models.generated_problem import GeneratedProblem
from app.schemas.generation_schema import GeneratedProblemBase

class GeneratedProblemRepository:
    def __init__(self, db: Session):
        self.db = db

    async def create(self, problem: GeneratedProblemBase) -> GeneratedProblem:
        db_problem = GeneratedProblem(**problem.model_dump())
        self.db.add(db_problem)
        self.db.commit()
        self.db.refresh(db_problem)
        return db_problem

    async def get_by_id(self, problem_id: int) -> Optional[GeneratedProblem]:
        return self.db.query(GeneratedProblem).filter(GeneratedProblem.id == problem_id).first()

    async def get_by_generated_problem_id(self, generated_problem_id: str) -> Optional[GeneratedProblem]:
        return self.db.query(GeneratedProblem).filter(GeneratedProblem.generated_problem_id == generated_problem_id).first()

    async def get_all(self) -> List[GeneratedProblem]:
        return self.db.query(GeneratedProblem).all()

    async def update_status(self, problem_id: int, status: str) -> Optional[GeneratedProblem]:
        db_problem = self.db.query(GeneratedProblem).filter(GeneratedProblem.id == problem_id).first()
        if db_problem:
            db_problem.status = status
            self.db.commit()
            self.db.refresh(db_problem)
        return db_problem

    async def delete(self, problem_id: int) -> bool:
        db_problem = self.db.query(GeneratedProblem).filter(GeneratedProblem.id == problem_id).first()
        if db_problem:
            self.db.delete(db_problem)
            self.db.commit()
            return True
        return False
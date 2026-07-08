from sqlalchemy.orm import Session
from typing import List, Optional
from app.models.problem import Problem
from app.schemas.problem_schema import ProblemCreate, ProblemUpdate


class ProblemRepository:
    def __init__(self, db: Session):
        self.db = db

    async def create(self, problem: ProblemCreate) -> Problem:
        db_problem = Problem(**problem.model_dump())
        self.db.add(db_problem)
        self.db.commit()
        self.db.refresh(db_problem)
        return db_problem

    def create_from_pdf(
        self,
        *,
        source_pdf_id: str,
        page_number: int,
        problem_number: Optional[int],
        elective_subject: str,
        problem_image_path: str,
        page_image_path: str,
        crop_box: dict,
        status: str = "unclassified",
        original_candidate_boxes: Optional[list] = None,
        raw_ocr_text: Optional[str] = None,
    ) -> Problem:
        db_problem = Problem(
            title="",
            source_type="pdf",
            source_pdf_id=source_pdf_id,
            page_number=page_number,
            problem_number=problem_number,
            elective_subject=elective_subject,
            problem_image_path=problem_image_path,
            page_image_path=page_image_path,
            crop_box=crop_box,
            original_candidate_boxes=original_candidate_boxes,
            small_type_ids=[],
            tags=[],
            raw_ocr_text=raw_ocr_text,
            latex_text=None,
            status=status,
        )
        self.db.add(db_problem)
        self.db.commit()
        self.db.refresh(db_problem)
        return db_problem

    async def get_by_id(self, problem_id: int) -> Optional[Problem]:
        return self.db.query(Problem).filter(Problem.id == problem_id).first()

    async def get_all(self) -> List[Problem]:
        return self.db.query(Problem).all()

    async def get_filtered(self, *, status: Optional[str] = None, source_pdf_id: Optional[str] = None, elective_subject: Optional[str] = None, page: int = 1, page_size: int = 20) -> List[Problem]:
        query = self.db.query(Problem)
        if status:
            query = query.filter(Problem.status == status)
        if source_pdf_id:
            query = query.filter(Problem.source_pdf_id == source_pdf_id)
        if elective_subject:
            query = query.filter(Problem.elective_subject == elective_subject)
        offset = (page - 1) * page_size
        return query.order_by(Problem.id.asc()).offset(offset).limit(page_size).all()

    async def get_by_source_pdf_id(self, source_pdf_id: str) -> List[Problem]:
        return self.db.query(Problem).filter(Problem.source_pdf_id == source_pdf_id).order_by(Problem.id.asc()).all()

    async def update(self, problem_id: int, problem_update: ProblemUpdate) -> Optional[Problem]:
        db_problem = self.db.query(Problem).filter(Problem.id == problem_id).first()
        if db_problem:
            for key, value in problem_update.model_dump(exclude_unset=True).items():
                setattr(db_problem, key, value)
            self.db.commit()
            self.db.refresh(db_problem)
        return db_problem

    async def delete(self, problem_id: int) -> bool:
        db_problem = self.db.query(Problem).filter(Problem.id == problem_id).first()
        if db_problem:
            db_problem.status = "excluded"
            self.db.commit()
            self.db.refresh(db_problem)
            return True
        return False
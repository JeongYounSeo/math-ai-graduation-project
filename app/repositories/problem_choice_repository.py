from sqlalchemy.orm import Session
from typing import List, Optional

from app.models.problem_choice import ProblemChoice, CHOICE_LABELS
from app.schemas.problem_choice_schema import ProblemChoiceCreate, ProblemChoiceUpdate


class ProblemChoiceRepository:
    def __init__(self, db: Session):
        self.db = db

    async def create(self, choice: ProblemChoiceCreate) -> ProblemChoice:
        db_choice = ProblemChoice(**choice.model_dump())
        self.db.add(db_choice)
        self.db.commit()
        self.db.refresh(db_choice)
        return db_choice

    async def get(self, choice_id: int) -> Optional[ProblemChoice]:
        return self.db.query(ProblemChoice).filter(ProblemChoice.id == choice_id).first()

    async def list_by_problem(self, problem_id: int) -> List[ProblemChoice]:
        return (
            self.db.query(ProblemChoice)
            .filter(ProblemChoice.problem_id == problem_id)
            .order_by(ProblemChoice.choice_index.asc())
            .all()
        )

    async def update(self, choice_id: int, choice_update: ProblemChoiceUpdate) -> Optional[ProblemChoice]:
        db_choice = self.db.query(ProblemChoice).filter(ProblemChoice.id == choice_id).first()
        if db_choice:
            for key, value in choice_update.model_dump(exclude_unset=True).items():
                setattr(db_choice, key, value)
            self.db.commit()
            self.db.refresh(db_choice)
        return db_choice

    async def delete(self, choice_id: int) -> bool:
        db_choice = self.db.query(ProblemChoice).filter(ProblemChoice.id == choice_id).first()
        if db_choice:
            self.db.delete(db_choice)
            self.db.commit()
            return True
        return False

    async def delete_by_problem(self, problem_id: int) -> int:
        deleted = self.db.query(ProblemChoice).filter(ProblemChoice.problem_id == problem_id).delete()
        self.db.commit()
        return deleted

    async def replace_choices_for_problem(self, problem_id: int, choices: List[str]) -> List[ProblemChoice]:
        """기존 choices를 전부 삭제하고 새 choices를 순서대로 저장한다.

        choice_index는 1부터 시작하고, choice_label은 ①②③④⑤ 순서로 부여한다.
        정답은 추측하지 않으므로 is_correct는 항상 null로 남긴다.
        비어 있거나 공백뿐인 항목은 건너뛴다 (malformed/empty 입력 방어).
        """
        self.db.query(ProblemChoice).filter(ProblemChoice.problem_id == problem_id).delete()

        created: List[ProblemChoice] = []
        index = 1
        for raw_text in choices or []:
            text = (raw_text or "").strip()
            if not text:
                continue
            label = CHOICE_LABELS[index - 1] if index - 1 < len(CHOICE_LABELS) else None
            db_choice = ProblemChoice(
                problem_id=problem_id,
                choice_index=index,
                choice_label=label,
                text=text,
                latex_text=text,
                normalized_text=text,
                is_correct=None,
                is_distractor=None,
            )
            self.db.add(db_choice)
            created.append(db_choice)
            index += 1

        self.db.commit()
        for db_choice in created:
            self.db.refresh(db_choice)
        return created

from sqlalchemy.orm import Session
from typing import List, Optional
from app.models.problem_choice import ProblemChoice
from app.models.problem import Problem

# ①②③④⑤ (U+2460 ~ U+2464). 5개 초과분은 라벨을 부여하지 않는다(None).
CIRCLED_LABELS = ["\u2460", "\u2461", "\u2462", "\u2463", "\u2464"]


class ProblemChoiceRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, data: dict) -> ProblemChoice:
        db_choice = ProblemChoice(**data)
        self.db.add(db_choice)
        self.db.commit()
        self.db.refresh(db_choice)
        return db_choice

    def get_by_problem_id(self, problem_id: int) -> List[ProblemChoice]:
        return (
            self.db.query(ProblemChoice)
            .filter(ProblemChoice.problem_id == problem_id)
            .order_by(ProblemChoice.choice_index.asc())
            .all()
        )

    def get_by_id(self, choice_id: int) -> Optional[ProblemChoice]:
        return (
            self.db.query(ProblemChoice)
            .filter(ProblemChoice.id == choice_id)
            .first()
        )

    def update(self, choice_id: int, data: dict) -> Optional[ProblemChoice]:
        db_choice = self.get_by_id(choice_id)
        if db_choice is None:
            return None

        # None 이 아닌 값만 갱신한다(부분 업데이트).
        for key, value in data.items():
            if value is not None and hasattr(db_choice, key):
                setattr(db_choice, key, value)

        self.db.commit()
        self.db.refresh(db_choice)
        return db_choice

    def delete(self, choice_id: int) -> bool:
        db_choice = self.get_by_id(choice_id)
        if db_choice is None:
            return False
        self.db.delete(db_choice)
        self.db.commit()
        return True

    def replace_choices_for_problem(
        self, problem_id: int, choices: List[str]
    ) -> List[ProblemChoice]:
        """해당 problem_id 의 기존 보기를 전부 삭제하고 입력 리스트로 재생성한다.

        - index 는 1부터 순서대로 부여.
        - choice_label 은 ①②③④⑤(최대 5개), 초과분은 None.
        - text 에 입력 문자열을 저장.
        - is_correct / is_distractor 는 **전부 None 유지(정답 추측 금지)**.
        - latex_text / normalized_text 는 None.
        """
        # 기존 보기 전부 삭제
        self.db.query(ProblemChoice).filter(
            ProblemChoice.problem_id == problem_id
        ).delete(synchronize_session=False)

        for i, choice_text in enumerate(choices):
            index = i + 1
            label = CIRCLED_LABELS[i] if i < len(CIRCLED_LABELS) else None
            db_choice = ProblemChoice(
                problem_id=problem_id,
                region_id=None,
                choice_index=index,
                choice_label=label,
                text=choice_text,
                latex_text=None,
                normalized_text=None,
                is_correct=None,  # 정답 추측 금지
                is_distractor=None,
            )
            self.db.add(db_choice)

        # Problem.choices / answer_type 동기화(비정규화 사본, 설계 §5-1).
        # 정본은 ProblemChoice 이며 이 컬럼은 조회 편의용. 어긋남 방지를 위해
        # 같은 트랜잭션에서 함께 갱신한다.
        problem = self.db.query(Problem).filter(Problem.id == problem_id).first()
        if problem is not None:
            problem.choices = list(choices)
            problem.answer_type = "multiple_choice"

        self.db.commit()
        return self.get_by_problem_id(problem_id)

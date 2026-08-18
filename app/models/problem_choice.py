from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


# choice_index(1부터) 순서에 대응하는 원문자 라벨
CHOICE_LABELS = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"]


class ProblemChoice(Base):
    """객관식 보기 하나의 의미 정보를 저장한다.

    프로젝트 관례상 DB-level ForeignKey()는 사용하지 않고,
    problem_id / region_id는 plain integer column으로 관계를 표현한다.
    """

    __tablename__ = "problem_choices"

    id = Column(Integer, primary_key=True, index=True)
    problem_id = Column(Integer, nullable=False, index=True)
    region_id = Column(Integer, nullable=True)
    choice_index = Column(Integer, nullable=False)
    choice_label = Column(String, nullable=True)
    text = Column(Text, nullable=True)
    latex_text = Column(Text, nullable=True)
    normalized_text = Column(Text, nullable=True)

    # 정답 여부. 답지/해설이 없으면 절대 추측해서 채우지 않는다 (null 유지).
    is_correct = Column(Boolean, nullable=True)
    is_distractor = Column(Boolean, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

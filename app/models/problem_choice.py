from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class ProblemChoice(Base):
    """객관식 보기(선택지)의 **의미**를 담는 모델(설계 §3).

    좌표/이미지는 ``ProblemRegion(choice_option)`` 이 담당하고, 이 모델은
    정답 여부/오답(distractor)/정규화 텍스트 등 의미 정보를 담는다.
    연결은 ``region_id``(nullable, plain int)로 표현한다.

    프로젝트 관례상 신규 모델은 DB-level ForeignKey 를 쓰지 않고 plain integer
    컬럼으로 관계를 표현한다(``problem_id``, ``region_id`` 모두 Integer + index).

    **정답 추측 금지**: 답지/해설이 없으면 ``is_correct`` 는 ``None`` 으로 유지한다.
    """

    __tablename__ = "problem_choices"

    id = Column(Integer, primary_key=True, index=True)
    problem_id = Column(Integer, nullable=False, index=True)  # plain int (FK 미사용)
    region_id = Column(Integer, nullable=True, index=True)  # choice_option region 연결
    choice_index = Column(Integer, nullable=False)  # 1부터 시작
    choice_label = Column(String, nullable=True)  # ①②③④⑤ 등
    text = Column(Text, nullable=True)
    latex_text = Column(Text, nullable=True)
    normalized_text = Column(Text, nullable=True)
    is_correct = Column(Boolean, nullable=True)  # 정답 추측 금지 → 기본 None
    is_distractor = Column(Boolean, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

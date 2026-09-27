from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, Float, ForeignKey
from sqlalchemy.sql import func
from app.core.database import Base
import enum


class RegionType(str, enum.Enum):
    """영역 유형.

    두 세대의 값이 공존한다:

    - **기존 6종(별칭 성격)**: Vision 추출 서비스/기존 테스트가 멤버명과 값
      (예: ``RegionType.QUESTION_TEXT.value == "QUESTION_TEXT"``)에 의존하므로
      값·이름 모두 절대 변경하지 않는다.
    - **신규 11종**: 좌표 승격/겹침 검증 설계(DESIGN_region_coord_validation.md §2)의
      정식 영역 유형. 소문자 스네이크 값(예: ``"full_problem"``)을 사용한다.

    두 세대의 값은 서로 겹치지 않으므로(예: 기존 ``"TABLE"`` vs 신규 ``"table"``)
    각각 독립 멤버로 존재하며, ``frozenset(rt.value for rt in RegionType)`` 는
    기존 값과 신규 값을 모두 포함한다.
    """

    # ---- 기존 6종 (절대 변경 금지: 기존 코드/테스트가 이 값에 의존) ----
    QUESTION_TEXT = "QUESTION_TEXT"
    DIAGRAM = "DIAGRAM"
    CHOICE_BOX = "CHOICE_BOX"
    STATEMENT_BOX = "STATEMENT_BOX"
    TABLE = "TABLE"
    OTHER = "OTHER"

    # ---- 신규 11종 (설계 §2 정식 유형) ----
    FULL_PROBLEM = "full_problem"
    QUESTION_BODY = "question_body"
    CONDITION_BOX = "condition_box"
    FIGURE = "figure"
    GRAPH = "graph"
    TABLE_NEW = "table"  # 주의: 기존 TABLE="TABLE"과 값이 다른 별도 멤버
    CHOICE_GROUP = "choice_group"
    CHOICE_OPTION = "choice_option"
    FORMULA = "formula"
    PASSAGE = "passage"
    UNKNOWN = "unknown"


class ProblemRegion(Base):
    __tablename__ = "problem_regions"

    id = Column(Integer, primary_key=True, index=True)
    problem_id = Column(Integer, ForeignKey("problems.id"), nullable=False, index=True)
    region_type = Column(String, nullable=False)  # RegionType.value
    order_index = Column(Integer, nullable=False)
    image_path = Column(String, nullable=True)
    bounding_box = Column(JSON, nullable=False)  # {left, top, right, bottom}
    ocr_text = Column(Text, nullable=True)
    latex_text = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)

    # ---- 좌표 승격 컬럼 (설계 §2). 모두 nullable, 점진 전환용 ----
    # corner 좌표 (x1,y1)=좌상단, (x2,y2)=우하단.
    x1 = Column(Float, nullable=True)
    y1 = Column(Float, nullable=True)
    x2 = Column(Float, nullable=True)
    y2 = Column(Float, nullable=True)
    page_width = Column(Float, nullable=True)
    page_height = Column(Float, nullable=True)
    # 부모-자식 관계는 plain integer 컬럼으로 표현(DB-level ForeignKey 미사용 관례).
    parent_region_id = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def set_box(self, corner, page_width=None, page_height=None):
        """corner 좌표를 x1..y2 컬럼과 bounding_box JSON에 **동시 기록**한다(설계 §2).

        Args:
            corner: ``(x1, y1, x2, y2)`` 튜플/리스트 또는
                ``{"x1","y1","x2","y2"}`` dict.
            page_width: 선택. 페이지 폭(정규화 좌표 파생용).
            page_height: 선택. 페이지 높이.

        bounding_box JSON 은 기존 규약 ``{left, top, right, bottom}`` 을 유지한다.
        """
        if isinstance(corner, dict):
            x1 = float(corner["x1"])
            y1 = float(corner["y1"])
            x2 = float(corner["x2"])
            y2 = float(corner["y2"])
        else:
            if len(corner) != 4:
                raise ValueError(f"corner 튜플은 길이 4여야 합니다: {corner!r}")
            x1, y1, x2, y2 = (float(v) for v in corner)

        # 컬럼 기록
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        if page_width is not None:
            self.page_width = float(page_width)
        if page_height is not None:
            self.page_height = float(page_height)

        # bounding_box JSON 동시 기록 ({left, top, right, bottom} 규약)
        self.bounding_box = {
            "left": x1,
            "top": y1,
            "right": x2,
            "bottom": y2,
        }

    def get_box(self):
        """corner 좌표 ``(x1, y1, x2, y2)`` 를 반환한다(설계 §2, 컬럼 우선).

        read 우선순위:
        1. x1..y2 컬럼이 모두 채워져 있으면 컬럼 값을 반환한다.
        2. 컬럼이 비어 있고 bounding_box JSON(``{left, top, right, bottom}``)이
           있으면 그것을 corner 로 변환해 반환한다.
        3. 둘 다 없으면 ``None`` 을 반환한다.
        """
        if (
            self.x1 is not None
            and self.y1 is not None
            and self.x2 is not None
            and self.y2 is not None
        ):
            return (
                float(self.x1),
                float(self.y1),
                float(self.x2),
                float(self.y2),
            )

        bb = self.bounding_box
        if isinstance(bb, dict) and {"left", "top", "right", "bottom"} <= set(bb):
            return (
                float(bb["left"]),
                float(bb["top"]),
                float(bb["right"]),
                float(bb["bottom"]),
            )
        return None

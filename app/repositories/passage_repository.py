from sqlalchemy.orm import Session
from typing import List, Optional, Tuple

from app.models.passage import Passage


# 지문 매칭 허용오차(픽셀). 네 좌표가 각각 이 값 이내여야 매칭으로 판정한다(Req 5.1).
CROP_BOX_TOLERANCE_PX = 5


def _normalize_crop_box(crop_box: Optional[dict]) -> Optional[Tuple[float, float, float, float]]:
    """crop_box dict를 (left, top, right, bottom) float 튜플로 정규화한다.

    두 표현을 모두 지원한다.
    - {left, top, right, bottom} 형태: 그대로 사용
    - {x, y, width, height} 형태: left=x, top=y, right=x+width, bottom=y+height 로 변환

    유효한 좌표를 얻을 수 없으면(빈 dict, None, 필요한 키 부재) None을 반환하며,
    이 경우 호출부에서 비매칭으로 처리한다.
    """
    if not crop_box or not isinstance(crop_box, dict):
        return None

    # left/top/right/bottom 표현 우선
    if all(k in crop_box for k in ("left", "top", "right", "bottom")):
        try:
            return (
                float(crop_box["left"]),
                float(crop_box["top"]),
                float(crop_box["right"]),
                float(crop_box["bottom"]),
            )
        except (TypeError, ValueError):
            return None

    # x/y/width/height 표현
    if all(k in crop_box for k in ("x", "y", "width", "height")):
        try:
            x = float(crop_box["x"])
            y = float(crop_box["y"])
            width = float(crop_box["width"])
            height = float(crop_box["height"])
            return (x, y, x + width, y + height)
        except (TypeError, ValueError):
            return None

    return None


def _boxes_match(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> bool:
    """네 좌표가 각각 허용오차 이내(<=)이면 True. 하나라도 초과하면 False(필요충분, Req 5.1)."""
    return all(abs(a[i] - b[i]) <= CROP_BOX_TOLERANCE_PX for i in range(4))


class PassageRepository:
    def __init__(self, db: Session):
        self.db = db

    def find_matching(
        self,
        source_pdf_id: int,
        page_number: int,
        crop_box: dict,
    ) -> Optional[Passage]:
        """같은 source_pdf_id·page_number이고 crop_box 네 좌표(left, top, right, bottom)가
        각각 5px 이내로 일치하는 기존 지문을 탐색한다.

        하나라도 5px를 초과하면 비매칭이다(필요충분, Req 5.1). 대상 crop_box가
        정규화 불가하거나 후보 지문의 crop_box가 null/빈 값이면 해당 후보는 비매칭이다.
        첫 매칭 지문을 반환하고, 매칭이 없으면 None을 반환한다.
        """
        target = _normalize_crop_box(crop_box)
        if target is None:
            return None

        candidates: List[Passage] = (
            self.db.query(Passage)
            .filter(
                Passage.source_pdf_id == source_pdf_id,
                Passage.page_number == page_number,
            )
            .all()
        )

        for candidate in candidates:
            candidate_box = _normalize_crop_box(candidate.crop_box)
            if candidate_box is None:
                continue
            if _boxes_match(target, candidate_box):
                return candidate

        return None

    def create(self, passage_data: dict) -> Passage:
        db_passage = Passage(**passage_data)
        self.db.add(db_passage)
        self.db.commit()
        self.db.refresh(db_passage)
        return db_passage

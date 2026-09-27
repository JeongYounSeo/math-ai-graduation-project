from sqlalchemy.orm import Session
from typing import List

from app.models.problem_region_item import ProblemRegionItem


class ProblemRegionItemRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, item_data: dict) -> ProblemRegionItem:
        db_item = ProblemRegionItem(**item_data)
        self.db.add(db_item)
        self.db.commit()
        self.db.refresh(db_item)
        return db_item

    def get_by_region_id(self, region_id: int) -> List[ProblemRegionItem]:
        return (
            self.db.query(ProblemRegionItem)
            .filter(ProblemRegionItem.region_id == region_id)
            .order_by(ProblemRegionItem.order_index.asc())
            .all()
        )

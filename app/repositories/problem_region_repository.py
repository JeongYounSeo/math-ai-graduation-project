from sqlalchemy.orm import Session
from typing import List
from app.models.problem_region import ProblemRegion
from app.models.problem_region_item import ProblemRegionItem


class ProblemRegionRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, region_data: dict) -> ProblemRegion:
        db_region = ProblemRegion(**region_data)
        self.db.add(db_region)
        self.db.commit()
        self.db.refresh(db_region)
        return db_region

    def get_by_problem_id(self, problem_id: int) -> List[ProblemRegion]:
        return (
            self.db.query(ProblemRegion)
            .filter(ProblemRegion.problem_id == problem_id)
            .order_by(ProblemRegion.order_index.asc())
            .all()
        )

    def delete_by_problem_id(self, problem_id: int) -> int:
        # Collect the ids of regions belonging to this problem so we can clean up
        # their child items first. The models do not declare ON DELETE CASCADE, so
        # with PRAGMA foreign_keys=ON we must remove child rows before the parents
        # to avoid FK violations / orphaned problem_region_items.
        region_ids = [
            row[0]
            for row in self.db.query(ProblemRegion.id)
            .filter(ProblemRegion.problem_id == problem_id)
            .all()
        ]

        if not region_ids:
            return 0

        # Delete child items belonging to these regions first.
        self.db.query(ProblemRegionItem).filter(
            ProblemRegionItem.region_id.in_(region_ids)
        ).delete(synchronize_session=False)

        # Then delete the regions themselves.
        deleted_count = (
            self.db.query(ProblemRegion)
            .filter(ProblemRegion.problem_id == problem_id)
            .delete(synchronize_session=False)
        )

        self.db.commit()
        return deleted_count

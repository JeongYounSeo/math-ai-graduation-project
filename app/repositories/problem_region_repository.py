from sqlalchemy.orm import Session
from typing import List, Optional

from app.models.problem import Problem
from app.models.problem_region import ProblemRegion
from app.schemas.problem_region_schema import ProblemRegionCreate, ProblemRegionUpdate


class ProblemRegionRepository:
    def __init__(self, db: Session):
        self.db = db

    async def create(self, region: ProblemRegionCreate) -> ProblemRegion:
        db_region = ProblemRegion(**region.model_dump())
        self.db.add(db_region)
        self.db.commit()
        self.db.refresh(db_region)
        return db_region

    async def get(self, region_id: int) -> Optional[ProblemRegion]:
        return self.db.query(ProblemRegion).filter(ProblemRegion.id == region_id).first()

    async def list_by_problem(self, problem_id: int) -> List[ProblemRegion]:
        return (
            self.db.query(ProblemRegion)
            .filter(ProblemRegion.problem_id == problem_id)
            .order_by(ProblemRegion.order_index.asc(), ProblemRegion.id.asc())
            .all()
        )

    async def list_by_problem_and_type(self, problem_id: int, region_type: str) -> List[ProblemRegion]:
        return (
            self.db.query(ProblemRegion)
            .filter(ProblemRegion.problem_id == problem_id, ProblemRegion.region_type == region_type)
            .order_by(ProblemRegion.order_index.asc(), ProblemRegion.id.asc())
            .all()
        )

    async def update(self, region_id: int, region_update: ProblemRegionUpdate) -> Optional[ProblemRegion]:
        db_region = self.db.query(ProblemRegion).filter(ProblemRegion.id == region_id).first()
        if db_region:
            for key, value in region_update.model_dump(exclude_unset=True).items():
                setattr(db_region, key, value)
            self.db.commit()
            self.db.refresh(db_region)
        return db_region

    async def delete(self, region_id: int) -> bool:
        db_region = self.db.query(ProblemRegion).filter(ProblemRegion.id == region_id).first()
        if db_region:
            self.db.delete(db_region)
            self.db.commit()
            return True
        return False

    async def delete_by_problem(self, problem_id: int) -> int:
        deleted = (
            self.db.query(ProblemRegion)
            .filter(ProblemRegion.problem_id == problem_id)
            .delete()
        )
        self.db.commit()
        return deleted

    def create_full_problem_region_from_problem(self, problem: Problem) -> Optional[ProblemRegion]:
        """Problem으로부터 full_problem region을 생성한다 (동기 메서드).

        problem_repository.create_from_pdf()가 동기 메서드이기 때문에 이 메서드도
        같은 흐름에서 바로 호출할 수 있도록 동기로 작성한다 (기존 create_from_pdf 관례와 동일).
        이미 해당 problem에 full_problem region이 있으면 중복 생성하지 않는다.
        """
        if not problem.problem_image_path:
            return None

        existing = (
            self.db.query(ProblemRegion)
            .filter(ProblemRegion.problem_id == problem.id, ProblemRegion.region_type == "full_problem")
            .first()
        )
        if existing:
            return existing

        crop_box = problem.crop_box or {}
        x1 = crop_box.get("x")
        y1 = crop_box.get("y")
        x2 = (crop_box.get("x") + crop_box.get("width")) if crop_box.get("x") is not None and crop_box.get("width") is not None else None
        y2 = (crop_box.get("y") + crop_box.get("height")) if crop_box.get("y") is not None and crop_box.get("height") is not None else None

        page_width, page_height = self._try_read_image_size(problem.page_image_path)

        db_region = ProblemRegion(
            problem_id=problem.id,
            region_type="full_problem",
            label="전체 문제",
            order_index=0,
            page_number=problem.page_number,
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
            page_width=page_width,
            page_height=page_height,
            image_path=problem.problem_image_path,
            cropped_image_path=problem.problem_image_path,
            extracted_text=problem.raw_ocr_text,
            latex_text=problem.latex_text,
            normalized_text=None,
            provider=None,
            confidence=None,
        )
        self.db.add(db_region)
        self.db.commit()
        self.db.refresh(db_region)
        return db_region

    @staticmethod
    def _try_read_image_size(image_path: Optional[str]):
        """가능하면 page 이미지 크기를 읽어온다. 실패해도 region 생성 자체는 막지 않는다."""
        if not image_path:
            return None, None
        try:
            from PIL import Image

            with Image.open(image_path) as img:
                return float(img.width), float(img.height)
        except Exception:
            return None, None

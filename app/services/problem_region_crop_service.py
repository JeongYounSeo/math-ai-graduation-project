from pathlib import Path
from typing import Optional

from PIL import Image

from app.core.storage import get_region_storage_dir
from app.models.problem import Problem
from app.models.problem_region import ProblemRegion


class ProblemRegionCropService:
    def crop_and_save(self, region: ProblemRegion, source_image_path: Optional[str]) -> str:
        """source_image_path에서 region.x1/y1/x2/y2 좌표로 잘라내
        uploads/regions/{problem_id}/{region_id}.png 에 저장하고 경로를 반환한다.

        x1~y2 중 하나라도 None이면 ValueError.
        """
        if any(coord is None for coord in (region.x1, region.y1, region.x2, region.y2)):
            raise ValueError("region 좌표(x1, y1, x2, y2)가 모두 있어야 crop할 수 있습니다.")

        if not source_image_path:
            raise ValueError("crop할 source 이미지 경로가 없습니다.")

        source_path = Path(source_image_path)
        if not source_path.exists():
            raise ValueError(f"source 이미지가 존재하지 않습니다: {source_image_path}")

        with Image.open(source_path) as image:
            left, right = sorted((region.x1, region.x2))
            top, bottom = sorted((region.y1, region.y2))
            left = max(0, int(round(left)))
            top = max(0, int(round(top)))
            right = min(image.width, int(round(right)))
            bottom = min(image.height, int(round(bottom)))

            if right <= left or bottom <= top:
                raise ValueError("region 좌표가 이미지 범위를 벗어났습니다.")

            cropped = image.crop((left, top, right, bottom))

            output_dir = get_region_storage_dir(region.problem_id)
            output_path = output_dir / f"{region.id}.png"
            cropped.save(output_path)

        return str(output_path)


def resolve_source_image_path(region: ProblemRegion, problem: Problem) -> Optional[str]:
    """region의 좌표계에 맞는 source 이미지 경로를 고른다.

    page_width/page_height와 함께 좌표가 저장된 region(예: full_problem)은
    페이지 이미지 기준 좌표라는 기존 관례를 따라 page_image_path를 사용한다.
    그렇지 않으면 problem 좌표계로 들어온 것으로 보고 problem_image_path를 사용한다.
    """
    if region.page_width is not None and region.page_height is not None and problem.page_image_path:
        return problem.page_image_path
    return problem.problem_image_path or problem.page_image_path

from typing import List, Optional

from PIL import Image

from app.core.storage import get_pdf_storage_path
from app.models.problem import Problem
from app.services.region_detectors.base import DetectedRegion, RegionDetector

# find_tables()는 실제 표가 아니라 여러 줄로 정렬된 본문 텍스트를 표로 오탐하는
# 경우가 있다 - 특히 문제 전체(혹은 페이지 전체)를 통째로 하나의 "표"로 잡는 경우가
# 실측(실제 수능형 PDF)에서 관찰됐다. clip 영역 대부분을 차지하는 결과는 실제 표라기엔
# 너무 크므로 걸러낸다.
_MAX_TABLE_AREA_RATIO = 0.85


class PDFGeometryRegionDetector(RegionDetector):
    """PDF 원본에 임베드된 이미지/표의 실제 배치 좌표를 직접 읽어 region을 찾는 detector.

    비전 LLM처럼 픽셀 좌표를 추측하지 않는다 - PyMuPDF로 원본 PDF 페이지를 다시 열어
    문제 crop 범위(clip) 안에 있는 임베디드 이미지(get_image_info)와 표(find_tables)의
    정확한 좌표를 그대로 읽어 problem-image-local 픽셀 좌표로 환산한다.

    problem.source_pdf_id/page_number/crop_box가 없으면(수동 등록 문제) 이 방식을
    적용할 수 없으므로 빈 리스트를 반환한다 (에러가 아니라 정상적인 "해당없음").
    """

    provider_name = "pdf-geometry-region-detector"

    async def detect(self, problem: Problem) -> List[DetectedRegion]:
        if not (problem.source_pdf_id and problem.page_number and problem.crop_box):
            return []
        if not problem.page_image_path:
            return []

        import fitz

        doc = fitz.open(get_pdf_storage_path(problem.source_pdf_id))
        try:
            page = doc[problem.page_number - 1]

            with Image.open(problem.page_image_path) as page_img:
                page_w, page_h = page_img.size
            scale_x = page_w / page.rect.width
            scale_y = page_h / page.rect.height

            crop_box = problem.crop_box
            clip = fitz.Rect(
                crop_box["x"] / scale_x,
                crop_box["y"] / scale_y,
                (crop_box["x"] + crop_box["width"]) / scale_x,
                (crop_box["y"] + crop_box["height"]) / scale_y,
            )

            detected: List[DetectedRegion] = []

            for img in page.get_image_info(xrefs=True):
                rect = fitz.Rect(img["bbox"])
                if clip.intersects(rect):
                    region = self._to_region(
                        "figure", rect, scale_x, scale_y, crop_box,
                        reason="PDF에 임베드된 이미지의 실제 배치 좌표",
                    )
                    if region is not None:
                        detected.append(region)

            clip_area = clip.width * clip.height
            for table in page.find_tables(clip=clip).tables:
                rect = fitz.Rect(table.bbox)
                if clip_area > 0 and (rect.width * rect.height) > _MAX_TABLE_AREA_RATIO * clip_area:
                    continue  # clip 대부분을 덮는 결과는 본문 텍스트 오탐일 가능성이 높음
                region = self._to_region(
                    "table", rect, scale_x, scale_y, crop_box,
                    reason="PDF 내장 표 구조 탐지 결과",
                )
                if region is not None:
                    detected.append(region)

            return detected
        finally:
            doc.close()

    @staticmethod
    def _to_region(
        region_type: str,
        rect,
        scale_x: float,
        scale_y: float,
        crop_box: dict,
        reason: str,
    ) -> Optional[DetectedRegion]:
        """PDF point 좌표(rect) -> page-pixel -> problem-image-local pixel로 환산한다.

        crop_box 범위를 벗어나면 clamp하고, clamp 후 폭/높이가 0 이하가 되면
        (겹치는 부분이 사실상 없는 경우) None을 반환해 호출부에서 건너뛰게 한다.
        """
        x1 = rect.x0 * scale_x - crop_box["x"]
        y1 = rect.y0 * scale_y - crop_box["y"]
        x2 = rect.x1 * scale_x - crop_box["x"]
        y2 = rect.y1 * scale_y - crop_box["y"]

        x1 = max(0.0, min(crop_box["width"], x1))
        x2 = max(0.0, min(crop_box["width"], x2))
        y1 = max(0.0, min(crop_box["height"], y1))
        y2 = max(0.0, min(crop_box["height"], y2))

        if x2 - x1 <= 0 or y2 - y1 <= 0:
            return None

        return DetectedRegion(
            region_type=region_type,
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
            confidence=0.9,
            reason=reason,
        )

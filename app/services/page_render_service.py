from pathlib import Path
from typing import List, Tuple, Any

from PIL import Image

from app.core.storage import get_page_storage_dir


class PageRenderService:
    def render_pdf_pages(self, pdf_path: Path, source_pdf_id: str, zoom: float = 2.0) -> List[Tuple[Path, Any]]:
        """
        PDF 페이지를 이미지로 렌더링하고 page 객체와 함께 반환한다.
        반환: [(page_image_path, page_object), ...]
        """
        rendered_paths: List[Tuple[Path, Any]] = []
        page_dir = get_page_storage_dir(source_pdf_id)

        try:
            import fitz
        except ModuleNotFoundError:
            fitz = None

        if fitz is not None:
            doc = fitz.open(pdf_path)
            for page_number, page in enumerate(doc, start=1):
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
                image_path = page_dir / f"page_{page_number:03d}.png"
                pix.save(str(image_path))
                rendered_paths.append((image_path, page))
            # doc은 의도적으로 닫지 않는다. 반환된 page 객체는 이후 crop 영역의
            # 텍스트 추출(page.get_textbox)에 계속 쓰이는데, Document를 닫으면
            # 그 page 객체들이 더 이상 유효하지 않게 된다.
            return rendered_paths

        # Fallback for environments where PyMuPDF is unavailable.
        image = Image.new("RGB", (800, 1000), color=(255, 255, 255))
        image_path = page_dir / "page_001.png"
        image.save(image_path)
        rendered_paths.append((image_path, None))
        return rendered_paths

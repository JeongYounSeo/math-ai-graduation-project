from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def save_image(image, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return output_path


def load_image(image_path: Path):
    return Image.open(image_path)


def save_debug_overlay(image_arr: np.ndarray, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), image_arr)
    return output_path


def get_debug_output_path(page_image_path: Path, page_number: int, suffix: str = "debug") -> Path:
    source_pdf_id = page_image_path.parent.name if page_image_path.parent.name else "unknown"
    base_dir = page_image_path.parents[2] if len(page_image_path.parents) > 2 else Path("uploads")
    return base_dir / "debug" / source_pdf_id / f"page_{page_number:03d}_{suffix}.png"


def draw_boxes_overlay(
    image_arr: np.ndarray,
    boxes: list,
    color: tuple = (0, 0, 255),
    label_prefix: str = "",
) -> np.ndarray:
    """디버그용으로 이미지 위에 (x1, y1, x2, y2) box들을 그린 사본을 반환한다."""
    overlay = image_arr.copy()
    for index, box in enumerate(boxes, start=1):
        x1, y1, x2, y2 = int(box["x1"]), int(box["y1"]), int(box["x2"]), int(box["y2"])
        cv2.rectangle(overlay, (x1, y1), (x2, y2), color, 2)
        label = f"{label_prefix}{index}"
        cv2.putText(overlay, label, (x1 + 5, max(15, y1 + 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    return overlay

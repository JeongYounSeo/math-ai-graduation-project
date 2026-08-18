import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class DetectedProblemNumber:
    problem_number: int
    page_number: int
    x: float
    y: float
    width: float
    height: float
    column: str  # "left" or "right"


def detect_problem_numbers(page_image_path: Path) -> list[DetectedProblemNumber]:
    """이미지 기반 문제 번호 인식 스텁 (미사용)."""
    return []


def detect_problem_numbers_from_pdf_page(page: Any, page_number: int) -> list[DetectedProblemNumber]:
    """
    PyMuPDF page.get_text("words")로부터 문제 번호를 감지한다.

    - word 단위로 "1.", "2.", ... "30." 패턴만 인식한다.
    - 페이지 번호와 선택지 번호(①, ②, ③), "20" 같은 단순 숫자는 제외한다.
    - 페이지 좌우 컬럼은 page.rect.width / 2 기준으로 나눈다.
    """
    try:
        words = page.get_text("words")
    except Exception:
        return []

    if not words:
        return []

    page_width = getattr(page.rect, "width", 0) or 0
    column_threshold = page_width / 2 if page_width else 0
    detected_numbers: list[DetectedProblemNumber] = []

    for word in words:
        if len(word) < 5:
            continue

        x0, y0, x1, y1, text, *_ = word
        cleaned = str(text).strip()
        if not cleaned:
            continue

        if not re.fullmatch(r"\d{1,2}\.", cleaned):
            continue

        problem_num = int(cleaned[:-1])
        if problem_num < 1 or problem_num > 30:
            continue

        if y0 < 50:
            continue

        if len(cleaned[:-1]) == 2 and problem_num not in {10, 20, 30}:
            continue

        if problem_num >= 20 and (y0 > 700 or x0 > 500):
            continue

        column = "left" if column_threshold and x0 < column_threshold else "right"
        detected_numbers.append(
            DetectedProblemNumber(
                problem_number=problem_num,
                page_number=page_number,
                x=float(x0),
                y=float(y0),
                width=float(x1 - x0),
                height=float(y1 - y0),
                column=column,
            )
        )

    detected_numbers.sort(key=lambda d: (d.column, d.y, d.x))
    print(f"[page {page_number}] detected problem numbers: {[d.problem_number for d in detected_numbers]}")
    return detected_numbers

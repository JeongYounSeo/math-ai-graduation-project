from typing import Optional

from app.models.problem import Problem
from app.models.source_pdf import SourcePDF

# math-ai의 elective_subject 값 -> theorem-bank 과목 토큰.
# theorem-bank 쪽 유일한 기존 예시가 "calc2"(미적분)라 그것만 확실하고,
# probstat/geom은 아직 theorem-bank에 전례가 없는 추정 토큰 - theorem-bank 쪽
# 컨벤션이 실제로 생기면 그때 맞춰 조정할 것. "common"은 단일 과목 토큰이
# 존재하지 않아 의도적으로 매핑하지 않는다(None).
_SUBJECT_TOKEN_MAP: dict[str, Optional[str]] = {
    "calculus": "calc2",
    "probability_statistics": "probstat",
    "geometry": "geom",
    "common": None,
}


def build_theorem_bank_problem_id(
    problem: Problem, source_pdf: Optional[SourcePDF]
) -> Optional[str]:
    """'<exam_slug>-<year>-<subject>-<번호>' 형식의 theorem-bank problem_id를 만든다.

    필요한 값 중 하나라도 없으면 None을 반환한다 (예외 아님) - 많은 Problem이
    (예: common 과목, 수동 등록으로 번호가 없는 경우) 영구적으로 매핑 불가능한
    것이 정상이므로, "아직 매핑 안 됨"을 에러가 아닌 값으로 표현한다.
    """
    year = problem.year
    number = problem.problem_number
    subject_token = _SUBJECT_TOKEN_MAP.get(problem.elective_subject or "")
    exam_slug = source_pdf.exam_slug if source_pdf else None

    if not (year and number and subject_token and exam_slug):
        return None

    return f"{exam_slug}-{year}-{subject_token}-{number}"

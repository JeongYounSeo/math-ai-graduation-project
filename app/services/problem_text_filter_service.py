"""crop 후보를 Problem으로 저장하기 전, 텍스트 기반으로 '문제답게 보이는지' 판단한다.

OpenCV crop 단계는 레이아웃(위치/여백)만 보고 후보를 만들기 때문에, "확인 사항"
안내 박스나 "제2교시 수학 영역" 같은 시험지 머리말이 여전히 후보로 남을 수 있다.
이 모듈은 PDF의 실제 텍스트(PyMuPDF)를 crop 영역 기준으로 추출해서, 문제에서
흔히 쓰이는 표현(구하시오, 옳은 것은?, [3점] 등)과 안내문에서 흔히 쓰이는 표현을
비교해 저장 여부를 결정한다. OCR/LLM은 사용하지 않는다.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

POSITIVE_KEYWORDS = [
    "구하시오",
    "찾으시오",
    "값은",
    "것은",
    "옳은 것",
    "알맞은",
    "몇 개인가",
    "확률은",
    "넓이",
    "길이",
    "최댓값",
    "최솟값",
    "최대",
    "최소",
    "[2점]",
    "[3점]",
    "[4점]",
    "?",
]

# 배점 표기는 문제일 가능성이 특히 높은 신호라서 일반 positive keyword 점수(+2)에
# 더해 추가 가산점을 준다.
SCORE_BRACKET_KEYWORDS = ["[2점]", "[3점]", "[4점]"]

NEGATIVE_KEYWORDS = [
    "확인 사항",
    "답안지",
    "해당란",
    "이어서",
    "선택과목인지 확인",
    "제2교시",
    "수학 영역",
    "5지선다형",
    "단답형",
    "문제지",
]

# 이 표현이 나오면 점수와 무관하게 즉시 제외한다 (시험 안내/답안지 영역이 명확함).
IMMEDIATE_REJECT_KEYWORDS = ["확인 사항", "답안지"]

# trailing instruction section을 잘라내는 기준이 되는 마커. 마지막 페이지의
# 30번 문제처럼 문제 본문 뒤에 "* 확인 사항" 안내 박스가 붙는 경우를 처리한다.
INSTRUCTION_SECTION_MARKERS = ["확인 사항", "답안지의 해당란", "답안지"]

# "확인 사항"류 마커가 텍스트 앞부분(전체 길이의 20% 이내)에 나타나거나, 그 앞의
# 실제 내용이 30자 미만이면 crop 전체가 안내문일 가능성이 높다고 보고 그대로 drop한다.
INSTRUCTION_NEAR_START_RATIO = 0.20
INSTRUCTION_MIN_PRECEDING_LENGTH = 30

# 문제 번호 패턴: 텍스트 시작 또는 공백(줄바꿈 포함) 뒤에 오는 "17." 같은 표기만 인정해서,
# 페이지 번호나 보기 번호(①②③ 등)와 혼동하지 않는다.
PROBLEM_NUMBER_PATTERN = re.compile(r"(^|\s)([1-9]|[12][0-9]|30)\.")

MIN_TEXT_LENGTH = 10
SAVE_SCORE_THRESHOLD = 3

POSITIVE_KEYWORD_SCORE = 2
SCORE_BRACKET_BONUS = 3
PROBLEM_NUMBER_SCORE = 2
NEGATIVE_KEYWORD_SCORE = -5


@dataclass
class ProblemTextFilterResult:
    should_save: bool
    score: int
    extracted_text: str
    positive_matches: list = field(default_factory=list)
    negative_matches: list = field(default_factory=list)
    reason: str = ""
    instruction_section_removed: bool = False


def strip_trailing_instruction_section(text: str) -> tuple:
    """텍스트 안에 "확인 사항", "답안지의 해당란" 등 안내문 마커가 등장하면
    그 위치 이후를 제거한다.

    30번 문제 아래에 "* 확인 사항" 박스가 붙어 있는 crop처럼, 문제 본문과
    안내문이 한 후보에 같이 들어있는 경우를 위한 것이다. 반환값:
    (cleaned_text, instruction_section_removed)
    """
    earliest_index = None
    for marker in INSTRUCTION_SECTION_MARKERS:
        idx = text.find(marker)
        if idx != -1 and (earliest_index is None or idx < earliest_index):
            earliest_index = idx

    if earliest_index is None:
        return text, False

    return text[:earliest_index], True


class ProblemTextFilter:
    """추출된 텍스트만 보고 crop 후보가 실제 '문제'인지 판단한다."""

    def evaluate_text(self, text: str) -> ProblemTextFilterResult:
        extracted_text = text or ""
        stripped = extracted_text.strip()

        cleaned_text, instruction_removed = strip_trailing_instruction_section(stripped)

        if instruction_removed:
            preceding_text = cleaned_text.strip()
            relative_position = (len(cleaned_text) / len(stripped)) if stripped else 0.0
            instruction_too_close_to_start = (
                relative_position <= INSTRUCTION_NEAR_START_RATIO
                or len(preceding_text) < INSTRUCTION_MIN_PRECEDING_LENGTH
            )
            if instruction_too_close_to_start:
                # 안내문 마커 앞에 실질적인 문제 본문이 거의 없다 -> crop 전체가
                # 안내문/답안지 영역일 가능성이 높으므로 기존처럼 즉시 제외한다.
                return ProblemTextFilterResult(
                    should_save=False,
                    score=0,
                    extracted_text=extracted_text,
                    positive_matches=[],
                    negative_matches=[],
                    reason="instruction/footer candidate",
                    instruction_section_removed=True,
                )
            evaluation_text = preceding_text
        else:
            evaluation_text = stripped

        positive_matches: list[str] = []
        negative_matches: list[str] = []
        score = 0

        for keyword in NEGATIVE_KEYWORDS:
            if keyword in evaluation_text:
                negative_matches.append(keyword)
                score += NEGATIVE_KEYWORD_SCORE

        for keyword in POSITIVE_KEYWORDS:
            if keyword in evaluation_text:
                positive_matches.append(keyword)
                score += POSITIVE_KEYWORD_SCORE

        for bracket_keyword in SCORE_BRACKET_KEYWORDS:
            if bracket_keyword in evaluation_text:
                score += SCORE_BRACKET_BONUS

        if PROBLEM_NUMBER_PATTERN.search(evaluation_text):
            score += PROBLEM_NUMBER_SCORE

        if any(keyword in evaluation_text for keyword in IMMEDIATE_REJECT_KEYWORDS):
            # cleaned_text를 만들고 남은 부분에도 여전히 안내문 표현이 있다면
            # (예: 앞부분에 별도로 "답안지"가 또 언급된 경우) 즉시 제외한다.
            return ProblemTextFilterResult(
                should_save=False,
                score=score,
                extracted_text=extracted_text,
                positive_matches=positive_matches,
                negative_matches=negative_matches,
                reason="instruction/footer candidate",
                instruction_section_removed=instruction_removed,
            )

        if len(evaluation_text) < MIN_TEXT_LENGTH:
            return ProblemTextFilterResult(
                should_save=False,
                score=score,
                extracted_text=extracted_text,
                positive_matches=positive_matches,
                negative_matches=negative_matches,
                reason="text too short",
                instruction_section_removed=instruction_removed,
            )

        should_save = score >= SAVE_SCORE_THRESHOLD
        reason = "problem-like text" if should_save else "insufficient problem-likeness score"

        return ProblemTextFilterResult(
            should_save=should_save,
            score=score,
            extracted_text=extracted_text,
            positive_matches=positive_matches,
            negative_matches=negative_matches,
            reason=reason,
            instruction_section_removed=instruction_removed,
        )


def extract_text_from_pdf_region(page: Optional[object], crop_box: dict, image_size: tuple) -> str:
    """image 좌표계의 crop_box를 PDF 좌표계로 변환한 뒤 해당 영역의 텍스트를 추출한다.

    page는 PyMuPDF의 fitz.Page 객체를 기대한다. page가 없거나(스캔 PDF 등)
    변환/추출 과정에서 실패하면 빈 문자열을 반환한다 (OCR로 대체하지 않는다).
    """
    if page is None:
        return ""

    image_width, image_height = image_size
    if image_width <= 0 or image_height <= 0:
        return ""

    try:
        page_rect = page.rect
        scale_x = page_rect.width / image_width
        scale_y = page_rect.height / image_height

        x0 = crop_box["x"] * scale_x
        y0 = crop_box["y"] * scale_y
        x1 = (crop_box["x"] + crop_box["width"]) * scale_x
        y1 = (crop_box["y"] + crop_box["height"]) * scale_y

        import fitz

        rect = fitz.Rect(x0, y0, x1, y1)
        text = page.get_textbox(rect)
        return text or ""
    except Exception:
        return ""

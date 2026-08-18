from app.services.problem_text_filter_service import (
    ProblemTextFilter,
    extract_text_from_pdf_region,
    strip_trailing_instruction_section,
)


def test_problem_with_number_and_score_bracket_is_saved():
    text_filter = ProblemTextFilter()

    result = text_filter.evaluate_text("17. 함수 f(x)에 대하여 f(1)의 값을 구하시오. [3점]")

    assert result.should_save is True
    assert "구하시오" in result.positive_matches


def test_question_mark_with_score_bracket_is_saved():
    text_filter = ProblemTextFilter()

    result = text_filter.evaluate_text("다음 중 옳은 것은? [4점]")

    assert result.should_save is True


def test_confirmation_and_answer_sheet_text_is_not_saved():
    text_filter = ProblemTextFilter()

    result = text_filter.evaluate_text("확인 사항 답안지의 해당란에 마킹하시오.")

    assert result.should_save is False
    assert result.reason == "instruction/footer candidate"


def test_exam_header_text_is_not_saved():
    text_filter = ProblemTextFilter()

    result = text_filter.evaluate_text("제2교시 수학 영역 5지선다형")

    assert result.should_save is False


def test_empty_text_is_not_saved():
    text_filter = ProblemTextFilter()

    result = text_filter.evaluate_text("")

    assert result.should_save is False


def test_score_bracket_only_text_is_too_short_and_not_saved():
    text_filter = ProblemTextFilter()

    result = text_filter.evaluate_text("[3점]")

    assert len("[3점]") < 10
    assert result.should_save is False
    assert result.reason == "text too short"


def test_problem_number_value_and_score_bracket_combo_is_saved():
    text_filter = ProblemTextFilter()

    result = text_filter.evaluate_text("23. 이차함수의 최댓값은 얼마인지 구하시오. [2점]")

    assert result.should_save is True
    assert result.score >= 3


def test_negative_keyword_outweighs_a_lone_positive_keyword():
    text_filter = ProblemTextFilter()

    result = text_filter.evaluate_text("문제지 배부 5지선다형 답안지 작성 요령 안내문입니다.")

    assert result.should_save is False


def test_problem_followed_by_confirmation_box_is_still_saved():
    """마지막 페이지 30번 문제 아래에 '* 확인 사항' 안내 박스가 붙어도,
    앞부분에 실제 문제 텍스트가 있으면 저장해야 한다."""
    text_filter = ProblemTextFilter()
    text = (
        "30. 함수 f(x)에 대하여 x=1에서의 접선의 기울기의 값을 구하시오. [4점]\n"
        "* 확인 사항\n"
        "답안지의 해당란에 형별과 수험 번호를 정확히 표시했는지 확인하시오."
    )

    result = text_filter.evaluate_text(text)

    assert result.should_save is True
    assert result.instruction_section_removed is True
    assert "구하시오" in result.positive_matches


def test_problem_29_followed_by_confirmation_notice_is_still_saved():
    text_filter = ProblemTextFilter()
    text = (
        "29. 삼각형 ABC의 넓이를 구하시오. 이때 옳은 것은? [4점]\n"
        "확인 사항\n"
        "이어서 선택과목 문제지가 배부됩니다."
    )

    result = text_filter.evaluate_text(text)

    assert result.should_save is True
    assert result.instruction_section_removed is True


def test_confirmation_box_only_text_is_not_saved():
    """안내 박스 텍스트만 있는(문제 본문이 없는) 후보는 여전히 drop해야 한다."""
    text_filter = ProblemTextFilter()
    text = (
        "* 확인 사항\n"
        "답안지의 해당란에 형별과 수험 번호를 정확히 표시했는지 확인하시오."
    )

    result = text_filter.evaluate_text(text)

    assert result.should_save is False
    assert result.instruction_section_removed is True


def test_short_preceding_text_before_confirmation_box_is_not_saved():
    """'확인 사항' 앞의 실제 내용이 30자 미만이면 crop 전체가 안내문일 가능성이 높으므로 drop한다."""
    text_filter = ProblemTextFilter()
    text = "이것은 문제. 확인 사항 답안지의 해당란에 표시하시오."

    preceding = text.split("확인 사항")[0].strip()
    assert len(preceding) < 30

    result = text_filter.evaluate_text(text)

    assert result.should_save is False
    assert result.instruction_section_removed is True


def test_strip_trailing_instruction_section_removes_marker_and_after():
    cleaned, removed = strip_trailing_instruction_section("문제 본문입니다. 확인 사항 답안지 안내 문구")

    assert removed is True
    assert cleaned == "문제 본문입니다. "
    assert "확인 사항" not in cleaned


def test_strip_trailing_instruction_section_returns_original_when_no_marker():
    cleaned, removed = strip_trailing_instruction_section("17. 값을 구하시오. [3점]")

    assert removed is False
    assert cleaned == "17. 값을 구하시오. [3점]"


def test_extract_text_from_pdf_region_returns_empty_string_when_page_is_none():
    text = extract_text_from_pdf_region(None, {"x": 0, "y": 0, "width": 100, "height": 100}, (800, 1000))

    assert text == ""


def test_extract_text_from_pdf_region_converts_image_coords_to_pdf_rect():
    import fitz

    class FakePage:
        def __init__(self):
            self.rect = fitz.Rect(0, 0, 600, 800)
            self.captured_rect = None

        def get_textbox(self, rect):
            self.captured_rect = rect
            return "17. 값을 구하시오."

    fake_page = FakePage()
    # image는 PDF 페이지의 2배 해상도로 렌더링됐다고 가정 (zoom=2.0)
    text = extract_text_from_pdf_region(fake_page, {"x": 100, "y": 200, "width": 300, "height": 100}, (1200, 1600))

    assert text == "17. 값을 구하시오."
    assert fake_page.captured_rect is not None
    assert fake_page.captured_rect.x0 == 50
    assert fake_page.captured_rect.y0 == 100
    assert fake_page.captured_rect.x1 == 200
    assert fake_page.captured_rect.y1 == 150

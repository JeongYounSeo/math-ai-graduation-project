from app.models.problem import Problem
from app.models.source_pdf import SourcePDF
from app.services.theorem_bank_id_service import build_theorem_bank_problem_id


def _problem(**overrides) -> Problem:
    defaults = dict(id=1, year=2025, problem_number=30, elective_subject="calculus")
    defaults.update(overrides)
    return Problem(**defaults)


def _source_pdf(**overrides) -> SourcePDF:
    defaults = dict(source_pdf_id="PDF_TEST", original_filename="x.pdf", stored_filename="x.pdf",
                     file_path="x.pdf", exam_slug="csat")
    defaults.update(overrides)
    return SourcePDF(**defaults)


def test_builds_id_when_all_fields_present():
    problem = _problem()
    source_pdf = _source_pdf()

    result = build_theorem_bank_problem_id(problem, source_pdf)

    assert result == "csat-2025-calc2-30"


def test_returns_none_when_source_pdf_missing():
    problem = _problem()

    result = build_theorem_bank_problem_id(problem, None)

    assert result is None


def test_returns_none_when_exam_slug_missing():
    problem = _problem()
    source_pdf = _source_pdf(exam_slug=None)

    result = build_theorem_bank_problem_id(problem, source_pdf)

    assert result is None


def test_returns_none_when_year_missing():
    problem = _problem(year=None)
    source_pdf = _source_pdf()

    result = build_theorem_bank_problem_id(problem, source_pdf)

    assert result is None


def test_returns_none_when_problem_number_missing():
    problem = _problem(problem_number=None)
    source_pdf = _source_pdf()

    result = build_theorem_bank_problem_id(problem, source_pdf)

    assert result is None


def test_returns_none_for_common_subject():
    problem = _problem(elective_subject="common")
    source_pdf = _source_pdf()

    result = build_theorem_bank_problem_id(problem, source_pdf)

    assert result is None


def test_returns_none_for_unmapped_subject():
    problem = _problem(elective_subject="some_new_subject")
    source_pdf = _source_pdf()

    result = build_theorem_bank_problem_id(problem, source_pdf)

    assert result is None


def test_probability_statistics_and_geometry_map_to_expected_tokens():
    source_pdf = _source_pdf()

    probstat = build_theorem_bank_problem_id(_problem(elective_subject="probability_statistics"), source_pdf)
    geom = build_theorem_bank_problem_id(_problem(elective_subject="geometry"), source_pdf)

    assert probstat == "csat-2025-probstat-30"
    assert geom == "csat-2025-geom-30"

from pathlib import Path

import pytest
from PIL import Image

from app.models.problem import Problem
from app.services.ocr_providers.mock import MockOCRProvider
from app.services.problem_ocr_service import ProblemOCRService


def _make_image(path: Path) -> Path:
    Image.new("RGB", (100, 100), "white").save(path)
    return path


@pytest.mark.asyncio
async def test_run_ocr_for_problem_uses_problem_image_path(tmp_path):
    image_path = _make_image(tmp_path / "problem.png")
    problem = Problem(id=1, problem_image_path=str(image_path), page_image_path=None)

    service = ProblemOCRService(MockOCRProvider(choices=["13/2", "27/4"]))
    result = await service.run_ocr_for_problem(problem)

    assert result.body_text is not None
    assert result.choices == ["13/2", "27/4"]
    assert result.provider_name == "mock"


@pytest.mark.asyncio
async def test_run_ocr_for_problem_falls_back_to_page_image_path(tmp_path):
    image_path = _make_image(tmp_path / "page.png")
    problem = Problem(id=1, problem_image_path=None, page_image_path=str(image_path))

    service = ProblemOCRService(MockOCRProvider())
    result = await service.run_ocr_for_problem(problem)

    assert result.body_text is not None


@pytest.mark.asyncio
async def test_run_ocr_for_problem_raises_without_any_image():
    problem = Problem(id=1, problem_image_path=None, page_image_path=None)
    service = ProblemOCRService(MockOCRProvider())

    with pytest.raises(ValueError):
        await service.run_ocr_for_problem(problem)


@pytest.mark.asyncio
async def test_run_ocr_for_problem_raises_when_image_file_missing(tmp_path):
    problem = Problem(id=1, problem_image_path=str(tmp_path / "missing.png"), page_image_path=None)
    service = ProblemOCRService(MockOCRProvider())

    with pytest.raises(FileNotFoundError):
        await service.run_ocr_for_problem(problem)

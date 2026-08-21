from pathlib import Path

import pytest
from PIL import Image

from app.models.problem_region import ProblemRegion


def _make_image(path: Path, size=(400, 300)) -> Path:
    Image.new("RGB", size, "white").save(path)
    return path


def test_crop_and_save_creates_file(tmp_path, monkeypatch):
    import app.core.storage as storage_module

    monkeypatch.setattr(storage_module, "DEFAULT_UPLOAD_ROOT", tmp_path / "uploads")
    from app.services.problem_region_crop_service import ProblemRegionCropService

    source = _make_image(tmp_path / "page.png")
    region = ProblemRegion(id=1, problem_id=42, region_type="figure", x1=10, y1=20, x2=110, y2=120)

    service = ProblemRegionCropService()
    output_path = service.crop_and_save(region, str(source))

    output = Path(output_path)
    assert output.exists()
    assert output == tmp_path / "uploads" / "regions" / "42" / "1.png"
    with Image.open(output) as img:
        assert img.size == (100, 100)


def test_crop_and_save_handles_swapped_coordinates(tmp_path, monkeypatch):
    import app.core.storage as storage_module

    monkeypatch.setattr(storage_module, "DEFAULT_UPLOAD_ROOT", tmp_path / "uploads")
    from app.services.problem_region_crop_service import ProblemRegionCropService

    source = _make_image(tmp_path / "page.png")
    # x2 < x1, y2 < y1 인 경우에도 crop이 가능해야 한다.
    region = ProblemRegion(id=2, problem_id=42, region_type="figure", x1=110, y1=120, x2=10, y2=20)

    service = ProblemRegionCropService()
    output_path = service.crop_and_save(region, str(source))

    with Image.open(output_path) as img:
        assert img.size == (100, 100)


def test_crop_and_save_without_coords_raises_value_error(tmp_path, monkeypatch):
    import app.core.storage as storage_module

    monkeypatch.setattr(storage_module, "DEFAULT_UPLOAD_ROOT", tmp_path / "uploads")
    from app.services.problem_region_crop_service import ProblemRegionCropService

    source = _make_image(tmp_path / "page.png")
    region = ProblemRegion(id=3, problem_id=42, region_type="choice_option", x1=None, y1=None, x2=None, y2=None)

    service = ProblemRegionCropService()
    with pytest.raises(ValueError):
        service.crop_and_save(region, str(source))


def test_crop_and_save_missing_source_image_raises_value_error(tmp_path, monkeypatch):
    import app.core.storage as storage_module

    monkeypatch.setattr(storage_module, "DEFAULT_UPLOAD_ROOT", tmp_path / "uploads")
    from app.services.problem_region_crop_service import ProblemRegionCropService

    region = ProblemRegion(id=4, problem_id=42, region_type="figure", x1=0, y1=0, x2=10, y2=10)
    service = ProblemRegionCropService()
    with pytest.raises(ValueError):
        service.crop_and_save(region, str(tmp_path / "missing.png"))

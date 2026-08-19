from pathlib import Path

import fitz
import pytest
from PIL import Image

from app.models.problem import Problem
from app.services.region_detectors.pdf_geometry import PDFGeometryRegionDetector


def _make_synthetic_pdf(pdf_path: Path, page_width_pt: float, page_height_pt: float, embed_image_path: Path,
                         embed_rect_pt: tuple) -> None:
    """point 크기(page_width_pt x page_height_pt)의 1페이지 PDF를 만들고
    embed_rect_pt(point 좌표) 위치에 embed_image_path 이미지를 삽입해 저장한다."""
    doc = fitz.open()
    page = doc.new_page(width=page_width_pt, height=page_height_pt)
    page.insert_image(fitz.Rect(*embed_rect_pt), filename=str(embed_image_path))
    doc.save(str(pdf_path))
    doc.close()


def _make_tiny_png(path: Path) -> Path:
    Image.new("RGB", (10, 10), "red").save(path)
    return path


def _setup(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOADS_ROOT", str(tmp_path / "uploads"))
    import app.core.storage as storage_module

    monkeypatch.setattr(storage_module, "DEFAULT_UPLOAD_ROOT", tmp_path / "uploads")
    return storage_module


@pytest.mark.asyncio
async def test_detect_converts_embedded_image_to_local_pixel_space(tmp_path, monkeypatch):
    storage_module = _setup(tmp_path, monkeypatch)

    # point space: 200 x 300 페이지, (60,120)-(140,220)에 이미지 삽입
    embed_png = _make_tiny_png(tmp_path / "embed.png")
    pdf_path = storage_module.get_pdf_storage_path("PDF_TEST")
    _make_synthetic_pdf(pdf_path, 200, 300, embed_png, (60, 120, 140, 220))

    # page-pixel space: 400 x 600 (scale=2.0)
    page_image_path = tmp_path / "page.png"
    Image.new("RGB", (400, 600), "white").save(page_image_path)

    problem = Problem(
        id=1,
        source_pdf_id="PDF_TEST",
        page_number=1,
        crop_box={"x": 50, "y": 100, "width": 300, "height": 400},
        page_image_path=str(page_image_path),
    )

    detector = PDFGeometryRegionDetector()
    regions = await detector.detect(problem)

    assert len(regions) == 1
    region = regions[0]
    assert region.region_type == "figure"
    assert region.x1 == pytest.approx(70.0)
    assert region.y1 == pytest.approx(140.0)
    assert region.x2 == pytest.approx(230.0)
    assert region.y2 == pytest.approx(340.0)
    assert region.confidence == 0.9


@pytest.mark.asyncio
async def test_detect_ignores_image_outside_crop_box(tmp_path, monkeypatch):
    storage_module = _setup(tmp_path, monkeypatch)

    embed_png = _make_tiny_png(tmp_path / "embed.png")
    pdf_path = storage_module.get_pdf_storage_path("PDF_TEST")
    # 이미지를 point space (10,10)-(30,30)에 삽입 - crop_box 범위 밖
    _make_synthetic_pdf(pdf_path, 200, 300, embed_png, (10, 10, 30, 30))

    page_image_path = tmp_path / "page.png"
    Image.new("RGB", (400, 600), "white").save(page_image_path)

    problem = Problem(
        id=1,
        source_pdf_id="PDF_TEST",
        page_number=1,
        crop_box={"x": 200, "y": 200, "width": 100, "height": 100},
        page_image_path=str(page_image_path),
    )

    detector = PDFGeometryRegionDetector()
    regions = await detector.detect(problem)

    assert regions == []


@pytest.mark.asyncio
async def test_detect_returns_empty_without_source_pdf_id(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)

    problem = Problem(
        id=1,
        source_pdf_id=None,
        page_number=None,
        crop_box=None,
        page_image_path=None,
    )

    detector = PDFGeometryRegionDetector()
    regions = await detector.detect(problem)

    assert regions == []


class _FakeTable:
    def __init__(self, bbox):
        self.bbox = bbox


class _FakeTableFinder:
    def __init__(self, tables):
        self.tables = tables


def _empty_pdf(storage_module, source_pdf_id: str, width_pt: float, height_pt: float) -> Path:
    doc = fitz.open()
    doc.new_page(width=width_pt, height=height_pt)
    pdf_path = storage_module.get_pdf_storage_path(source_pdf_id)
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.mark.asyncio
async def test_detect_keeps_small_table_within_clip(tmp_path, monkeypatch):
    storage_module = _setup(tmp_path, monkeypatch)
    _empty_pdf(storage_module, "PDF_TABLE_SMALL", 200, 300)

    page_image_path = tmp_path / "page.png"
    Image.new("RGB", (400, 600), "white").save(page_image_path)

    problem = Problem(
        id=1,
        source_pdf_id="PDF_TABLE_SMALL",
        page_number=1,
        crop_box={"x": 0, "y": 0, "width": 400, "height": 600},
        page_image_path=str(page_image_path),
    )

    # clip은 point space (0,0)-(200,300) 전체 - 표는 그 중 작은 일부(30,30)-(70,70)만 차지
    monkeypatch.setattr(
        fitz.Page, "find_tables",
        lambda self, clip=None: _FakeTableFinder([_FakeTable((30, 30, 70, 70))]),
    )

    detector = PDFGeometryRegionDetector()
    regions = await detector.detect(problem)

    table_regions = [r for r in regions if r.region_type == "table"]
    assert len(table_regions) == 1
    assert table_regions[0].x1 == pytest.approx(60.0)  # 30 * scale(2.0)
    assert table_regions[0].y1 == pytest.approx(60.0)


@pytest.mark.asyncio
async def test_detect_filters_out_table_spanning_almost_entire_clip(tmp_path, monkeypatch):
    """find_tables()가 본문 텍스트 전체를 표로 오탐하는 경우(실측 PDF에서 관찰됨)를
    걸러내는지 검증한다: clip 대부분을 덮는 결과는 무시해야 한다."""
    storage_module = _setup(tmp_path, monkeypatch)
    _empty_pdf(storage_module, "PDF_TABLE_HUGE", 200, 300)

    page_image_path = tmp_path / "page.png"
    Image.new("RGB", (400, 600), "white").save(page_image_path)

    problem = Problem(
        id=1,
        source_pdf_id="PDF_TABLE_HUGE",
        page_number=1,
        crop_box={"x": 0, "y": 0, "width": 400, "height": 600},
        page_image_path=str(page_image_path),
    )

    # clip과 거의 동일한 크기(point space (0,0)-(200,300))의 "표" - 오탐 시나리오
    monkeypatch.setattr(
        fitz.Page, "find_tables",
        lambda self, clip=None: _FakeTableFinder([_FakeTable((0, 0, 199, 299))]),
    )

    detector = PDFGeometryRegionDetector()
    regions = await detector.detect(problem)

    assert [r for r in regions if r.region_type == "table"] == []


@pytest.mark.asyncio
async def test_detect_returns_empty_when_no_tables_or_images(tmp_path, monkeypatch):
    storage_module = _setup(tmp_path, monkeypatch)

    doc = fitz.open()
    doc.new_page(width=200, height=300)
    pdf_path = storage_module.get_pdf_storage_path("PDF_EMPTY")
    doc.save(str(pdf_path))
    doc.close()

    page_image_path = tmp_path / "page.png"
    Image.new("RGB", (400, 600), "white").save(page_image_path)

    problem = Problem(
        id=1,
        source_pdf_id="PDF_EMPTY",
        page_number=1,
        crop_box={"x": 0, "y": 0, "width": 400, "height": 600},
        page_image_path=str(page_image_path),
    )

    detector = PDFGeometryRegionDetector()
    regions = await detector.detect(problem)

    assert regions == []

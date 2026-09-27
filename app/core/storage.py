from pathlib import Path
import os


DEFAULT_UPLOAD_ROOT = Path(os.getenv("UPLOADS_ROOT", "uploads"))


def ensure_upload_dirs() -> None:
    for relative_dir in ["pdfs", "pages", "problems"]:
        (DEFAULT_UPLOAD_ROOT / relative_dir).mkdir(parents=True, exist_ok=True)


def get_upload_path(*parts: str) -> Path:
    ensure_upload_dirs()
    return DEFAULT_UPLOAD_ROOT.joinpath(*parts)


def get_pdf_storage_path(source_pdf_id: str) -> Path:
    return get_upload_path("pdfs", f"{source_pdf_id}.pdf")


def get_page_storage_dir(source_pdf_id: str) -> Path:
    page_dir = get_upload_path("pages", source_pdf_id)
    page_dir.mkdir(parents=True, exist_ok=True)
    return page_dir


def get_problem_storage_dir(source_pdf_id: str) -> Path:
    problem_dir = get_upload_path("problems", source_pdf_id)
    problem_dir.mkdir(parents=True, exist_ok=True)
    return problem_dir


def _require_identifier(name: str, value) -> str:
    """Validate that an identifier is present and non-empty.

    Raises ValueError identifying the missing/empty identifier so callers can
    abort the save operation without writing any file (Requirement 10.3).
    """
    if value is None:
        raise ValueError(f"missing identifier: {name}")
    text = str(value).strip()
    if not text:
        raise ValueError(f"missing identifier: {name}")
    return text


def get_region_image_path(source_pdf_id, problem_id, region_id) -> Path:
    """Return the storage path for a region image.

    Path pattern: uploads/problems/{source_pdf_id}/{problem_id}/regions/{region_id}.png
    (Requirement 10.1).

    Every required identifier (source_pdf_id, problem_id, region_id) must be a
    non-empty value; if any is missing or empty, a ValueError identifying the
    missing identifier is raised and no directories are created and no file is
    written (Requirement 10.3).

    Writing an image to the returned fixed path overwrites any existing file at
    that path, retaining only the most recently saved image (Requirement 10.4).
    """
    source = _require_identifier("source_pdf_id", source_pdf_id)
    problem = _require_identifier("problem_id", problem_id)
    region = _require_identifier("region_id", region_id)
    region_dir = get_upload_path("problems", source, problem, "regions")
    region_dir.mkdir(parents=True, exist_ok=True)
    return region_dir / f"{region}.png"


def get_item_image_path(source_pdf_id, problem_id, item_id) -> Path:
    """Return the storage path for a labeled-item image.

    Path pattern: uploads/problems/{source_pdf_id}/{problem_id}/items/{item_id}.png
    (Requirement 10.2).

    Every required identifier (source_pdf_id, problem_id, item_id) must be a
    non-empty value; if any is missing or empty, a ValueError identifying the
    missing identifier is raised and no directories are created and no file is
    written (Requirement 10.3).

    Writing an image to the returned fixed path overwrites any existing file at
    that path, retaining only the most recently saved image (Requirement 10.4).
    """
    source = _require_identifier("source_pdf_id", source_pdf_id)
    problem = _require_identifier("problem_id", problem_id)
    item = _require_identifier("item_id", item_id)
    item_dir = get_upload_path("problems", source, problem, "items")
    item_dir.mkdir(parents=True, exist_ok=True)
    return item_dir / f"{item}.png"

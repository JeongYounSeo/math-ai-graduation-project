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

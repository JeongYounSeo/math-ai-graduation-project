"""TASK 2.5 — passages 모델 NOT NULL 제약(예시 기반).
TASK 3.4 — 스키마 생성 스모크 테스트.

db_session 픽스처는 인메모리 SQLite에 신규 스키마 테이블을 생성하고
`PRAGMA foreign_keys=ON`으로 FK를 강제한다.

Requirements: 9.2 (2.5), 9.6/9.7 (3.4)
"""

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.models.passage import Passage
from app.models.source_pdf import SourcePDF


def _make_source_pdf(db_session) -> SourcePDF:
    """유효한 source_pdfs 행을 하나 만들어 커밋하고 반환한다.

    Passage.source_pdf_id FK가 실제 부모를 참조하도록 하여, NOT NULL 제약만
    격리 검증할 수 있게 한다.
    """
    src = SourcePDF(
        source_pdf_id="PDF_TEST0001",
        original_filename="orig.pdf",
        stored_filename="stored.pdf",
        file_path="uploads/pdfs/PDF_TEST0001.pdf",
    )
    db_session.add(src)
    db_session.commit()
    db_session.refresh(src)
    return src


# ---------------------------------------------------------------------------
# TASK 2.5 — NOT NULL 제약 (Req 9.2)
# ---------------------------------------------------------------------------
def test_passage_null_source_pdf_id_rejected(db_session):
    # source_pdf_id=None → NOT NULL이 FK보다 먼저 발동한다.
    passage = Passage(
        source_pdf_id=None,
        page_number=1,
        passage_image_path="uploads/x.png",
    )
    db_session.add(passage)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_passage_null_page_number_rejected(db_session):
    src = _make_source_pdf(db_session)
    passage = Passage(
        source_pdf_id=src.id,
        page_number=None,
        passage_image_path="uploads/x.png",
    )
    db_session.add(passage)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_passage_null_image_path_rejected(db_session):
    src = _make_source_pdf(db_session)
    passage = Passage(
        source_pdf_id=src.id,
        page_number=1,
        passage_image_path=None,
    )
    db_session.add(passage)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_passage_optional_fields_nullable(db_session):
    # crop_box/ocr_text/latex_text는 null 허용: 나머지 필수 필드만 채우면 커밋 성공.
    src = _make_source_pdf(db_session)
    passage = Passage(
        source_pdf_id=src.id,
        page_number=2,
        passage_image_path="uploads/passage.png",
        crop_box=None,
        ocr_text=None,
        latex_text=None,
    )
    db_session.add(passage)
    db_session.commit()
    db_session.refresh(passage)

    assert passage.id is not None
    assert passage.crop_box is None
    assert passage.ocr_text is None
    assert passage.latex_text is None


# ---------------------------------------------------------------------------
# TASK 3.4 — 스키마 생성 스모크 테스트 (Req 9.6, 9.7)
# ---------------------------------------------------------------------------
def test_new_tables_exist(db_session):
    # db_session이 이미 create_all로 테이블을 생성했다. 세 신규 테이블이 존재해야 한다.
    inspector = inspect(db_session.get_bind())
    table_names = set(inspector.get_table_names())

    assert "passages" in table_names
    assert "problem_regions" in table_names
    assert "problem_region_items" in table_names

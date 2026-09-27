"""TASK 4.2 — PassageRepository.find_matching 속성 기반 테스트(Property 9).

지문 매칭은 네 좌표(left, top, right, bottom)가 각각 5px 이내일 때만(필요충분)
매칭으로 판정한다(Req 5.1).

hypothesis + 함수 스코프 DB 픽스처의 상호작용(예제마다 픽스처 재생성) 및
health check를 피하기 위해, db_session 픽스처를 @given 테스트에서 요청하지 않고
테스트 본문에서 인메모리 세션을 직접 구성한다. 외부 셋업(엔진/세션 생성 + 행 삽입)은
한 번만 실행되고, @given 데코레이트된 내부 함수만 여러 번 재실행된다.

Requirements: 5.1
"""

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.repositories.passage_repository import PassageRepository


# 기준 crop_box (left, top, right, bottom).
_BASE_BOX = {"left": 100, "top": 200, "right": 400, "bottom": 500}
_PAGE_NUMBER = 3


def _build_session():
    """conftest.db_session과 동일한 구성의 인메모리 SQLite 세션을 만든다."""
    from app.core.db_base import Base
    import app.models.source_pdf  # noqa: F401
    import app.models.passage  # noqa: F401
    import app.models.problem  # noqa: F401
    import app.models.problem_region  # noqa: F401
    import app.models.problem_region_item  # noqa: F401

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, Session()


def test_passage_matching_5px_tolerance():
    from app.models.source_pdf import SourcePDF
    from app.models.passage import Passage

    engine, session = _build_session()
    try:
        # FK 만족을 위한 유효 source_pdfs 행 1건.
        src = SourcePDF(
            source_pdf_id="PDF_MATCH0001",
            original_filename="orig.pdf",
            stored_filename="stored.pdf",
            file_path="uploads/pdfs/PDF_MATCH0001.pdf",
        )
        session.add(src)
        session.commit()
        session.refresh(src)

        # 기준 crop_box를 가진 지문 1건(외부 셋업, 한 번만 실행).
        stored = Passage(
            source_pdf_id=src.id,
            page_number=_PAGE_NUMBER,
            passage_image_path="uploads/passage.png",
            crop_box=dict(_BASE_BOX),
        )
        session.add(stored)
        session.commit()
        session.refresh(stored)

        repo = PassageRepository(session)
        source_pdf_id = src.id
        stored_id = stored.id

        # Feature: problem-region-vision-ocr, Property 9: 지문 매칭은 5픽셀 허용오차 규칙을 정확히 따른다
        @settings(max_examples=100)
        @given(
            d_left=st.integers(min_value=-8, max_value=8),
            d_top=st.integers(min_value=-8, max_value=8),
            d_right=st.integers(min_value=-8, max_value=8),
            d_bottom=st.integers(min_value=-8, max_value=8),
        )
        def check(d_left, d_top, d_right, d_bottom):
            candidate = {
                "left": _BASE_BOX["left"] + d_left,
                "top": _BASE_BOX["top"] + d_top,
                "right": _BASE_BOX["right"] + d_right,
                "bottom": _BASE_BOX["bottom"] + d_bottom,
            }
            # 필요충분: 네 델타가 모두 절댓값 5 이하일 때만 매칭.
            expected_match = all(
                abs(d) <= 5 for d in (d_left, d_top, d_right, d_bottom)
            )

            result = repo.find_matching(source_pdf_id, _PAGE_NUMBER, candidate)

            if expected_match:
                assert result is not None
                assert result.id == stored_id
            else:
                assert result is None

        check()
    finally:
        session.close()
        engine.dispose()

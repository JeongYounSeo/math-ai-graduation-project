from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.core.db_base import Base  # noqa: F401 (모델/테스트에서 재수출용으로 계속 사용)

engine = None
SessionLocal = None


def _set_sqlite_pragma(dbapi_conn, connection_record):
    """SQLite 연결마다 외래키 무결성을 강제한다(PRAGMA foreign_keys=ON)."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _init_engine():
    global engine, SessionLocal
    if engine is None or str(engine.url) != settings.DATABASE_URL:
        engine = create_engine(
            settings.DATABASE_URL,
            connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
        )
        # SQLite는 기본적으로 외래키를 강제하지 않으므로, sqlite URL일 때만
        # 새 엔진 인스턴스에 connect 이벤트를 등록해 연결마다 PRAGMA를 실행한다.
        if "sqlite" in settings.DATABASE_URL:
            event.listen(engine, "connect", _set_sqlite_pragma)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine


_init_engine()


def get_db():
    """데이터베이스 세션 의존성"""
    db = _init_engine()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def create_tables():
    """테이블 생성"""
    from app.models.problem import Problem
    from app.models.source_pdf import SourcePDF
    from app.models.concept_module import ConceptModule
    from app.models.solution_module import SolutionModule
    from app.models.type_combination import TypeCombination
    from app.models.generated_problem import GeneratedProblem
    from app.models.passage import Passage
    from app.models.problem_region import ProblemRegion
    from app.models.problem_region_item import ProblemRegionItem
    from app.models.problem_choice import ProblemChoice
    from app.models.crop_review import CropPageReview, CropProposal

    tables = [
        Problem.__table__,
        SourcePDF.__table__,
        ConceptModule.__table__,
        SolutionModule.__table__,
        TypeCombination.__table__,
        GeneratedProblem.__table__,
        Passage.__table__,
        ProblemRegion.__table__,
        ProblemRegionItem.__table__,
        ProblemChoice.__table__,
        CropPageReview.__table__,
        CropProposal.__table__,
    ]

    # 테이블을 하나씩 생성해, 실패 시 어떤 테이블에서 실패했는지 식별하고
    # 즉시 중단한다. checkfirst=True로 이미 존재하는 테이블은 건너뛰어
    # 부분 생성 상태를 남기지 않는다.
    engine = _init_engine()
    for table in tables:
        try:
            table.create(bind=engine, checkfirst=True)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"테이블 생성 실패: '{table.name}' 생성 중 오류가 발생하여 작업을 중단합니다."
            ) from exc

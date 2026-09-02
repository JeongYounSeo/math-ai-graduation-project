from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.core.db_base import Base  # noqa: F401 (모델/테스트에서 재수출용으로 계속 사용)

engine = None
SessionLocal = None


def _init_engine():
    global engine, SessionLocal
    if engine is None or str(engine.url) != settings.DATABASE_URL:
        engine = create_engine(
            settings.DATABASE_URL,
            connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
        )
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

    Base.metadata.create_all(
        bind=_init_engine(),
        tables=[
            Problem.__table__,
            SourcePDF.__table__,
            ConceptModule.__table__,
            SolutionModule.__table__,
            TypeCombination.__table__,
            GeneratedProblem.__table__,
        ],
    )
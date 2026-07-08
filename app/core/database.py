from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

# 베이스 클래스
Base = declarative_base()

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

    Base.metadata.create_all(bind=_init_engine(), tables=[Problem.__table__, SourcePDF.__table__])
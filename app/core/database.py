import importlib
import sys

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
    """테이블 생성

    이전에는 tables=[Problem.__table__, SourcePDF.__table__] 두 테이블만 명시적으로 생성하고 있어서
    ConceptModule/SolutionModule/TypeCombination/GeneratedProblem 테이블이 만들어지지 않고,
    해당 API 호출 시 'no such table' 500 에러가 발생하는 버그가 있었다.

    Base.metadata.create_all(bind=engine)처럼 전체 metadata를 한 번에 생성하는 방식은 쓰지 않는다.
    테스트 스위트가 DATABASE_URL을 바꿔가며 이 모듈을 importlib.reload()하는 패턴을 쓰는데,
    reload될 때마다 Base = declarative_base()가 다시 실행되어 새 MetaData가 만들어지는 반면
    이미 import되어 캐시된 모델 모듈들은 예전 Base(및 예전 MetaData)에 묶인 채로 남는다.
    그 결과 Base.metadata에는 테이블이 하나도 등록되지 않은 상태가 될 수 있다.
    각 모델의 __table__을 직접 넘기면 어느 Base에 묶여 있었는지와 무관하게 항상 정확히 생성된다.

    다만 GeneratedProblem.source_problem_id처럼 문자열 기반 ForeignKey("problems.id")를 쓰는
    컬럼은, 참조 대상 Problem 모델이 '다른 reload epoch'의 Base.metadata에 묶여 있으면
    같은 MetaData 안에서 "problems" 테이블을 찾지 못해 NoReferencedTableError가 난다.
    그래서 매번 모델 모듈을 강제로 reload해서 전부 지금 이 Base에 다시 묶은 뒤 생성한다.
    """

    def _ensure_model(module_name: str, class_name: str):
        module = sys.modules.get(module_name) or importlib.import_module(module_name)
        cls = getattr(module, class_name)
        if cls.metadata is not Base.metadata:
            # 이 클래스는 예전 reload epoch의 Base에 묶여 있다 -> 지금 Base로 다시 묶는다.
            module = importlib.reload(module)
            cls = getattr(module, class_name)
        return cls

    Problem = _ensure_model("app.models.problem", "Problem")
    SourcePDF = _ensure_model("app.models.source_pdf", "SourcePDF")
    ConceptModule = _ensure_model("app.models.concept_module", "ConceptModule")
    SolutionModule = _ensure_model("app.models.solution_module", "SolutionModule")
    TypeCombination = _ensure_model("app.models.type_combination", "TypeCombination")
    GeneratedProblem = _ensure_model("app.models.generated_problem", "GeneratedProblem")
    ProblemRegion = _ensure_model("app.models.problem_region", "ProblemRegion")
    ProblemChoice = _ensure_model("app.models.problem_choice", "ProblemChoice")

    Base.metadata.create_all(
        bind=_init_engine(),
        tables=[
            Problem.__table__,
            SourcePDF.__table__,
            ConceptModule.__table__,
            SolutionModule.__table__,
            TypeCombination.__table__,
            GeneratedProblem.__table__,
            ProblemRegion.__table__,
            ProblemChoice.__table__,
        ],
    )
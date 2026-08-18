from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.core.database import create_tables
from app.routers import (
    problem_router,
    solution_module_router,
    concept_module_router,
    type_combination_router,
    generation_router,
    analysis_router,
    pdf_import_router,
    problem_region_router,
    problem_choice_router,
)
import app.models.source_pdf  # noqa: F401

app = FastAPI(
    title="Math Problem Engine",
    description="AI 기반 수능 수학 문제 분석 및 유사문제 생성 시스템",
    version="1.0.0",
)

uploads_dir = Path("uploads")
uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")

static_dir = Path(__file__).resolve().parent / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# 데이터베이스 테이블 생성
create_tables()

# 라우터 등록
app.include_router(problem_router.router, prefix="/problems", tags=["Problems"])
app.include_router(problem_router.router, prefix="/api/problems", tags=["Problems"])
app.include_router(solution_module_router.router, prefix="/solution-modules", tags=["Solution Modules"])
app.include_router(concept_module_router.router, prefix="/concept-modules", tags=["Concept Modules"])
app.include_router(type_combination_router.router, prefix="/type-combinations", tags=["Type Combinations"])
app.include_router(generation_router.router, prefix="/generate", tags=["Generation"])
app.include_router(analysis_router.router, prefix="/analysis", tags=["Analysis"])
app.include_router(pdf_import_router.router)
app.include_router(problem_region_router.router)
app.include_router(problem_choice_router.router)


@app.get("/")
async def root():
    return {"message": "Math Problem Engine API"}


@app.get("/viewer")
async def viewer_page():
    return FileResponse(static_dir / "viewer.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
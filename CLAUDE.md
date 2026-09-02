# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project purpose

An engine that analyzes Korean CSAT (수능) math problems and generates new problems from reusable "소유형" (solution-type) modules — small solving-strategy units (trigger conditions, core concepts, solution steps, combination rules) rather than simple tags. See [README.md](README.md) for the full domain model (Problem, ConceptModule, SolutionModule, TypeCombination, GeneratedProblem).

## Commands

```bash
# install deps
pip install -r requirements.txt

# run the server
uvicorn app.main:app --reload
# API docs at http://localhost:8000/docs

# run all tests
python -m pytest tests/ -v

# run one test file
python -m pytest tests/test_pdf_import_flow.py -v

# run one test
python -m pytest tests/test_pdf_import_flow.py::test_pdf_upload_creates_source_pdf_and_problem_candidates -v
```

There is no lint/format/build config in this repo (no `pyproject.toml`, no configured linter).

**Windows/Python 3.14 note**: `pymupdf` may fail to compile without Visual Studio build tools. Services degrade gracefully when it's unavailable (e.g. `page_render_service` falls back to a blank PIL image), so tests can still run, but PDF-derived features (problem number detection, text filtering) will be skipped/no-ops without it.

## Architecture

### Layering

Strict one-directional dependency chain, per file/module (not per feature — see below for the two exceptions):

```
Router → Service → Repository → Model
              ↓
           Schema (Pydantic validation/serialization)
```

- **Router** (`app/routers/`): request/response only, delegates to a Service
- **Service** (`app/services/`): business logic
- **Repository** (`app/repositories/`): DB access only, one per model
- **Schema** (`app/schemas/`): Pydantic validation/serialization
- **Model** (`app/models/`): SQLAlchemy tables

### Two subsystems with very different maturity

The codebase currently has two halves that look similar (routers/services/repos exist for both) but are **not** at the same level of completeness. Do not assume one implies the other.

1. **PDF import pipeline — real, working image-processing code.** Entry point `PDFImportService.import_pdf` (`app/services/pdf_import_service.py`), driven by `POST /api/pdf-import/upload`:
   - `page_render_service.py` renders PDF pages to images via PyMuPDF, returning `(image_path, fitz_page)` pairs.
   - `problem_number_detector.py` regex-matches "1.", "2." ... against PyMuPDF text coordinates to detect problem numbers and left/right column layout.
   - `problem_block_grouping_service.py` (OpenCV `findContours`) groups raw content blocks into one crop candidate per problem, filtering header/footer/instruction-box zones.
   - `problem_crop_service.py` produces the final crop boxes, preferring number-based crops and falling back to layout heuristics (2/3-column) when detection is weak.
   - `crop_classifier_service.py` classifies each crop (`problem` / `header` / `footer` / `answer_choices` / `blank`) — only `MockCropClassifier` (a hand-written heuristic) is implemented; `VisionLLMCropClassifier` is a `NotImplementedError` stub for future vision-model integration.
   - `problem_text_filter_service.py` does a second, text-based pass (keyword scoring on PyMuPDF-extracted text — "구하시오", "[3점]", etc.) to reject non-problem candidates that survived the layout pass. No OCR/LLM involved.
   - `problem_candidate_merge_service.py` merges classified candidates (e.g. answer-choice blocks get merged into the preceding problem) into final `Problem` rows with `status="unclassified"`.
   - Files are written under `uploads/{pdfs,pages,problems}/...`, rooted at `UPLOADS_ROOT` env var (see `app/core/storage.py`), not hardcoded `uploads/`.

2. **AI analysis/generation subsystem — stubbed, not wired to any model.** `ocr_service.py`, `latex_service.py`, `classification_service.py`, `problem_analysis_service.py`, `solution_module_service.py`, `generation_service.py`, `verification_service.py` all build real prompts (see `app/prompts/` and `prompt_builder_service.py`) but then return **hardcoded mock data** instead of calling a model — every one of them is literally the same cosine-rule triangle example. `app/core/config.py` defines `OPENAI_API_KEY` but nothing in the codebase reads it — there is no actual LLM/OCR/vision call anywhere yet. When asked to "implement" analysis/generation/verification/classification, the prompt-building side already exists; what's missing is the actual model call replacing the mock return value.

### Database gotchas

- `app/core/database.py` keeps `engine`/`SessionLocal` as **module-level singletons**, re-initialized only if `DATABASE_URL` changes. Tests that need an isolated DB must `monkeypatch.setenv("DATABASE_URL", ...)` *and* `monkeypatch.setenv("UPLOADS_ROOT", ...)` before `importlib.reload(app.core.database)` and `importlib.reload(app.main)` — see `tests/test_pdf_import_flow.py` for the pattern. Just setting the env var without reloading will not switch the DB.
- `Base` (the SQLAlchemy declarative base) lives in `app/core/db_base.py`, not `app/core/database.py`, specifically so `importlib.reload(app.core.database)` doesn't create a second `Base`/`MetaData`. All models import `Base` via `app.core.database` (which re-exports it), but that import resolves to the same object across reloads. Don't move `Base`'s definition back into `database.py` — models imported before a reload and models imported for the first time after a reload would end up on different `MetaData` objects, breaking cross-model foreign keys (this actually happened when `GeneratedProblem`, which has a FK to `problems`, was added to `create_tables()`).
- `create_tables()` in `app/core/database.py` explicitly lists every model's table (`Problem`, `SourcePDF`, `ConceptModule`, `SolutionModule`, `TypeCombination`, `GeneratedProblem`). If you add a new model, add its table to this list too — it is not automatic.
- Default DB is `sqlite:///./math_problem_engine.db` (see `Settings.DATABASE_URL`).

### Routing note

`app/main.py` mounts `problem_router` twice, under both `/problems` and `/api/problems` prefixes — same endpoints, two paths. The PDF import and newer problem-listing docs in the README use the `/api/...` prefix.

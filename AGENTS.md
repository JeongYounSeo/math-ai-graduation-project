
# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

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

   **Exception (wired 2026-09-17):** `problem_ocr_apply_service.py` (`ProblemOcrApplyService.apply_ocr_result`) is now actually called at the end of the PDF import pipeline (after region-overlap hook 2 in `pdf_import_service.py`) and is exposed via `POST /{problem_id}/apply-ocr`. It does two side effects only: (1) if `answer_type=='multiple_choice'` with a non-empty `choices` list, it replaces `ProblemChoice` rows (and syncs the denormalized `Problem.choices`/`Problem.answer_type` columns); (2) if no `full_problem` region exists, it creates one from `crop_box`. It still does NOT call any model — `choices` come from the CHOICE_BOX region items via `PDFImportService._build_ocr_result_from_regions` (empty when Vision is not wired, so the path is a no-op then). `correct_answer` is never persisted (no answer guessing).

### Database gotchas

- `app/core/database.py` keeps `engine`/`SessionLocal` as **module-level singletons**, re-initialized only if `DATABASE_URL` changes. Tests that need an isolated DB must `monkeypatch.setenv("DATABASE_URL", ...)` *and* `monkeypatch.setenv("UPLOADS_ROOT", ...)` before `importlib.reload(app.core.database)` and `importlib.reload(app.main)` — see `tests/test_pdf_import_flow.py` for the pattern. Just setting the env var without reloading will not switch the DB.
- `Base` (the SQLAlchemy declarative base) lives in `app/core/db_base.py`, not `app/core/database.py`, specifically so `importlib.reload(app.core.database)` doesn't create a second `Base`/`MetaData`. All models import `Base` via `app.core.database` (which re-exports it), but that import resolves to the same object across reloads. Don't move `Base`'s definition back into `database.py` — models imported before a reload and models imported for the first time after a reload would end up on different `MetaData` objects, breaking cross-model foreign keys (this actually happened when `GeneratedProblem`, which has a FK to `problems`, was added to `create_tables()`).
- `create_tables()` in `app/core/database.py` explicitly lists every model's table (`Problem`, `SourcePDF`, `ConceptModule`, `SolutionModule`, `TypeCombination`, `GeneratedProblem`). If you add a new model, add its table to this list too — it is not automatic.
- Default DB is `sqlite:///./math_problem_engine.db` (see `Settings.DATABASE_URL`).
- **`problems` gained `choices` (JSON) and `answer_type` (String) columns (2026-09-17 migration, both nullable).** They are a denormalized copy of the `ProblemChoice` rows for read convenience; the normalized source of truth is still `ProblemChoice`. `ProblemChoiceRepository.replace_choices_for_problem` keeps them in sync in the same transaction. Existing DBs were migrated in place via `ALTER TABLE ADD COLUMN` (backup: `math_problem_engine.db.bak_*`). New DBs get them automatically from the model.

### Routing note

`app/main.py` mounts `problem_router` twice, under both `/problems` and `/api/problems` prefixes — same endpoints, two paths. The PDF import and newer problem-listing docs in the README use the `/api/...` prefix.


## Change log

### 2026-09-17 — apply_ocr wiring + Problem.choices schema extension
Wired the previously-orphaned `apply_ocr_result` into the flow and extended the schema:
1. **full_problem region auto-creation** — connected in `pdf_import_service.py` right after
   region-overlap hook 2. Works without Vision (needs only `crop_box`).
2. **choices adapter** — `PDFImportService._build_ocr_result_from_regions` assembles a
   `choices` list from CHOICE_BOX region items; empty ⇒ choice save is skipped (no regression).
3. **Problem.choices / answer_type columns** — added (nullable JSON/String). Reverses the
   earlier "Problem schema unchanged" decision that was recorded in
   `problem_ocr_apply_service.py` (docstring updated accordingly). Denormalized copy; source
   of truth remains `ProblemChoice`. `correct_answer` still not stored.
4. **`POST /{problem_id}/apply-ocr` endpoint** — added to `problem_router.py` (exposed under
   both `/problems/...` and `/api/problems/...`).

Tests: `tests/test_apply_ocr_integration.py` (6 cases). Existing 92 tests should still pass.

Follow-up (done 2026-09-17): the choices adapter now reads BOTH the new `choice_option`
region type (each option is its own region; text in ocr_text/latex_text; sorted by
order_index then box top; needs >=2) AND the legacy `CHOICE_BOX`+items shape. The new
`choice_option` path takes priority; `CHOICE_BOX` is the fallback. See
`PDFImportService._choices_from_choice_options` / `_choices_from_choice_box`.


### 2026-09-17 (2) — region 좌표 정규화(0~1) 버그픽스
Vision region 추출의 좌표계 버그를 수정. 증상: 세로로 긴 문제(예: 842x1954)에서
region bounding_box 가 이미지 상단에 쭈그러들어(모든 박스가 상단 ~26%에 몰림) DIAGRAM/TABLE
크롭이 엉뚱한 영역을 잘랐다. 원인: 원본 이미지를 그대로 Vision 에 보내면서 프롬프트가
실제 크기를 안 알려주고 "픽셀 좌표"를 요구 → Vision 이 ~800 스케일을 가정한 좌표를 반환 →
저장 시 원본(예: 1954px) 좌표로 그대로 해석. 수정(정규화 좌표 방식):
- `region_extraction_prompt.py`: bounding_box 를 0.0~1.0 정규화 비율 좌표로 요구(예시도 교체).
- `problem_region_extraction_service._parse_bounding_box(raw, img_w, img_h)`: 네 값이 모두
  <=1.0 이면 이미지 크기를 곱해 픽셀 복원. 하나라도 >1.0 이면 레거시 픽셀 좌표로 간주하고
  그대로 둔다(하위호환 — 재추출 안 한 기존 71개 region 안 깨짐).
- `_read_image_size()` 헬퍼 추가, extract_regions → _build_pending_regions 로 (img_w,img_h) 전달.
테스트: `tests/test_region_coord_normalization.py` (6 케이스). 기존 region 데이터는 재추출해야
새 좌표계로 통일됨(레거시는 그대로 동작).


### 2026-09-17 (3) — problem_regions 스키마 드리프트 수정 + 재추출 검증
**증상**: `POST /api/problems/{id}/extract-regions` 재추출 시
`sqlite3.OperationalError: table problem_regions has no column named x1` 로 영속화 실패.

**원인 (스키마 드리프트)**: `ProblemRegion` 모델에는 좌표 승격/겹침검증용 컬럼
`x1, y1, x2, y2, page_width, page_height, parent_region_id` 가 정의돼 있으나, 기존 DB
테이블에는 없었다. `create_tables()` 는 테이블이 **없을 때만** 생성하고 기존 테이블에
컬럼을 추가하지 않으므로(이 리포엔 Alembic 등 마이그레이션 도구 없음), 모델에 컬럼이
추가됐을 때 기존 DB용 ALTER 가 누락돼 발생. 재추출을 처음 실제로 돌려서야 드러났다.

**조치**: 7개 컬럼을 `ALTER TABLE problem_regions ADD COLUMN` 으로 추가
(x1..y2/page_width/page_height=FLOAT, parent_region_id=INTEGER).
백업: `math_problem_engine.db.bak_20260917_152213`. 전 10개 테이블 모델↔DB 정합 재확인 완료.

**재추출 검증 (좌표 정규화 실효 확인)**: problem 116(842x844) 재추출 성공. DIAGRAM region
의 bounding_box 가 top≈490, bottom=844(이미지 높이 전체)로 정확히 하단 그림 위에 정렬됨
— 수정 전 상단 ~26%로 쭈그러들던 버그가 해소됨을 실데이터로 확인. 4개 region(발문/조건/
질문/그림) 모두 실제 내용에 정렬. DIAGRAM 은 이미지 파일로 crop 저장됨.

**교훈 (재발 방지)**: 모델에 Column 을 추가할 때는 반드시 기존 DB용 `ALTER TABLE` 마이그레이션을
함께 수행할 것. `create_tables()` 는 신규 DB만 커버한다.

### 겹침검증 훅(ENABLE_REGION_OVERLAP_VALIDATION) 활성화 가능 상태
위 컬럼 추가로 훅 2(`_apply_region_overlap_validation`)가 이제 실제 동작 가능
(get_box()/set_box() 이 x1..y2 컬럼에 의존). 기본값은 여전히 False(회귀 0). "true" 로
켜면 재추출 시 validate_and_resolve(mode="regions") 로 shrink/reject/merge_if_contained/
clamp_to_parent 보정이 적용됨. fail-open 이라 켜도 안전. 표처럼 region 이 많은 복잡한 문제에
효과 큼. 켜기 전 116 등으로 on/off A/B 비교 권장.


### 2026-09-25 — 번호 기반 crop 연결 (바깥 층 정교화)
**배경**: 페이지→문제 crop 이 컬럼 이등분 폴백만 써서 박스가 헐렁하고 헤더가 섞였다.
problem_number 는 116개 전부 None 이었다.

**진단(2단계)**:
1. `detect_problem_numbers_from_pdf_page` 는 PyMuPDF words 로 "1."~"30." 을 정확히 감지하나
   **아무 데서도 호출 안 되는 고아 함수**였고, crop 은 MockCropClassifier 의 가짜 값(None 또는
   y<250 이면 1)을 썼다.
2. 감지 로직에 `두자리 & 10/20/30 아님 -> continue` 필터가 있어 11~19,21~29 를 전부 버렸다
   (수능은 30번까지라 진짜 문제번호를 죽이는 버그). 제거 후 진단 재실행: 12개 -> 30개 전부 감지.

**수정**:
- `problem_number_detector.py`: 두 자리 배제 필터 제거(마침표 형태만 통과시키므로 페이지번호는
  이미 걸러짐, problem_num>30 이 상한 담당).
- `problem_crop_service.py`: `_crop_by_problem_numbers()` 추가 + crop_problem_candidates 에서
  밀도 분할보다 **먼저** 시도. 번호 y좌표 x RENDER_ZOOM(2.0) 로 렌더 이미지 좌표 변환(번호 감지는
  PDF 원본 842 좌표, crop_box 는 렌더 1684 좌표). 컬럼별 정렬, 번호 i~i+1 직전을 한 문제로,
  마지막은 페이지 바닥까지. **번호 <2개면 None -> 기존 밀도/폴백**(스캔본/논술 하위호환, 회귀 0).
- `problem_candidate_merge_service.py`: candidate.problem_number 를 classifier 값보다 우선.
- `crop_classifier_service.py`: 가짜 problem_number=1 휴리스틱 제거.

**⚠️ RENDER_ZOOM 결합**: problem_crop_service.RENDER_ZOOM(2.0) 은 page_render_service.
render_pdf_pages 의 zoom=2.0 과 반드시 일치해야 한다. 한쪽만 바꾸면 crop 좌표가 어긋난다.

**한계(설계상 의도)**: 번호가 텍스트로 읽히는 문제지에만 정확. 스캔본(텍스트 레이어 없음)·수리논술
(번호 체계 없음)·번호가 PUA 로 깨진 PDF 는 폴백으로 넘어감. 그 경우 Vision 기반 crop 이 별도 필요.

**테스트**: tests/test_number_based_crop.py (page1 좌표 변환/컬럼분리/바닥까지/번호<2개 None).

**남은 검증**: 실제 crop 재실행(PDF 재처리)으로 절취선 before/after 비교 필요. 기존 저장된 116개
문제는 재처리해야 새 번호 기반 crop 이 반영됨.

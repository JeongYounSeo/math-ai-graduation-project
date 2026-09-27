
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

## Problem region decomposition (Claude Vision OCR/LaTeX)

The `problem-region-vision-ocr` feature decomposes a single problem image into an ordered set of typed regions and extracts each region's OCR/LaTeX text plus labeled sub-items. It sits on top of the existing layered architecture (Router → Service → Repository → Model + Pydantic Schema) and does not modify `classification_service`, `generation_service`, or `verification_service`.

### Behavior

- **Input consumed**: a single problem image path (`Problem.problem_image_path`). `ProblemRegionExtractionService.extract_regions(problem)` is the orchestration entry point; if the image cannot be read it returns an error result and creates no regions.
- **Single structured Vision call**: the service makes exactly one `ClaudeVisionClient.extract(image_path, prompt)` call per image under normal operation. Region detection, per-region OCR/LaTeX text, and labeled-item parsing all come back in that one structured JSON response. The prompt is built by `app/prompts/region_extraction_prompt.py`. The client enforces a 60s timeout and retries on `timeout`/`429`/`5xx` up to 2 times, waiting 1–30s before each retry (bounded backoff). Malformed JSON or an exhausted retry budget yields a failed result with no partial data persisted; a failed image marks only that problem `failed` and does not abort the rest of the import pipeline.
- **Decomposition output (typed regions)**: each region is assigned exactly one `region_type` from `{QUESTION_TEXT, DIAGRAM, CHOICE_BOX, STATEMENT_BOX, TABLE, OTHER}` (`RegionType` in `app/models/problem_region.py`).
  - **Text regions** (`QUESTION_TEXT`, `CHOICE_BOX`, `STATEMENT_BOX`, `TABLE`) get `ocr_text`; when math is present it is stored in `latex_text` with the math wrapped in `$...$` inline delimiters (plain text with no delimiters when there is no math). `confidence`, when returned, is clamped to `0.0–1.0`, otherwise left null. A text-extraction failure isolates to that region (its `ocr_text`/`latex_text` stay null with an error noted) and does not stop the others.
  - **DIAGRAM regions** are cropped from the source image to a separate image file (path recorded in `image_path`) and are **not** OCR'd — `ocr_text` and `latex_text` stay null. Bounding boxes past the image edge are clamped to the bounds; if a clamped box is under 1px wide/tall or has non-positive area the crop is skipped, `image_path` is left empty, and an error is noted.
  - **CHOICE_BOX / STATEMENT_BOX regions** are split into labeled items. Labels are preserved verbatim ("①"–"⑤" for choices, "ㄱ"/"ㄴ"/"ㄷ" for `<보기>` statements).
- **Region ordering**: `order_index` is 0-based, contiguous, and unique, assigned by sorting bounding boxes by `top` ascending, then `left` ascending. Labeled items within a region use the same 0-based contiguous scheme in reading order (top→bottom, then left→right).
- **Passage reuse**: shared passages live in the `passages` table and are reused via `PassageRepository.find_matching(source_pdf_id, page_number, crop_box)`, which matches when all four crop-box coordinates are within a 5px tolerance (same `source_pdf_id` and `page_number`). A match reuses the existing passage and skips re-OCR; no match creates exactly one new passage row.
- **Assembled cache**: the legacy single-text fields on `problems` (`raw_text`, `raw_ocr_text`, `latex_text`) remain and are repopulated by concatenating region contents in `order_index` order (regions are the source of truth). If cache assembly fails the three existing field values are preserved; a problem with no regions leaves the cache empty without error.
- **Safe fallback (no credentials)**: when neither `ANTHROPIC_API_KEY` nor `CLAUDE_API_KEY` is set, the service falls back to the existing stub behavior, makes **no network call**, returns success, and logs a single warning.
- **Query endpoint**: `GET /api/problems/{problem_id}/regions` returns the ordered regions with nested labeled items (`ProblemRegionsResponse`). Unknown `problem_id` → 404; an existing problem with no regions → 200 with an empty list.
- **Config**: `ANTHROPIC_API_KEY` (falls back to `CLAUDE_API_KEY`) and `CLAUDE_VISION_MODEL` (default `claude-3-5-sonnet-latest`) are exposed as `@property` accessors on `Settings` (`app/core/config.py`). `anthropic` is pinned in `requirements.txt`; the credential placeholders are documented in `.env.example`.
- **DB migration strategy**: recreate the local dev DB — delete `math_problem_engine.db` and re-run `create_tables()` (which must list `Passage`, `ProblemRegion`, `ProblemRegionItem` in its manual `tables=[...]` registry). This is a destructive, local-only step; it is not applied to production data. For sqlite, `_init_engine()` registers a `connect` event that runs `PRAGMA foreign_keys=ON` so the DB enforces FK integrity.

### Schema additions

New table **`passages`**:

| Field | Type | Required / Optional |
| --- | --- | --- |
| `id` | int (PK) | required |
| `source_pdf_id` | int (FK → `source_pdfs.id`) | required |
| `page_number` | int | required |
| `passage_image_path` | str | required |
| `crop_box` | JSON | optional (nullable) |
| `ocr_text` | text | optional (nullable) |
| `latex_text` | text | optional (nullable) |
| `created_at` | datetime | server default |
| `updated_at` | datetime | optional (on update) |

New table **`problem_regions`**:

| Field | Type | Required / Optional |
| --- | --- | --- |
| `id` | int (PK) | required |
| `problem_id` | int (FK → `problems.id`) | required |
| `region_type` | str (`RegionType` value) | required |
| `order_index` | int | required |
| `image_path` | str | optional (nullable) |
| `bounding_box` | JSON (`{left, top, right, bottom}`) | required |
| `ocr_text` | text | optional (nullable) |
| `latex_text` | text | optional (nullable) |
| `confidence` | float (0.0–1.0) | optional (nullable) |
| `created_at` | datetime | server default |
| `updated_at` | datetime | optional (on update) |

New table **`problem_region_items`**:

| Field | Type | Required / Optional |
| --- | --- | --- |
| `id` | int (PK) | required |
| `region_id` | int (FK → `problem_regions.id`) | required |
| `label` | str | required |
| `order_index` | int | required |
| `text` | text | optional (nullable) |
| `latex` | text | optional (nullable) |
| `image_path` | str | optional (nullable) |
| `created_at` | datetime | server default |
| `updated_at` | datetime | optional (on update) |

Added to the existing **`problems`** table:

| Field | Type | Required / Optional |
| --- | --- | --- |
| `passage_id` | int (FK → `passages.id`) | optional (nullable) |

### Known limitations

- **Simplified passage deduplication.** Matching is by same `source_pdf_id` + `page_number` + crop-box within 5px tolerance only. Near-duplicate passages with larger offsets, or the same passage appearing on a different page, are stored as separate rows. *Observable effect*: some duplicate OCR work and duplicate passage rows. In addition, the current `region_extraction_prompt` does not emit a top-level `passage` object, so passage reuse is dormant until the prompt is extended. *Observable effect*: `problems.passage_id` stays null and no `passages` rows are created through the pipeline yet.
- **`source_pdf_id` type mismatch.** `Problem.source_pdf_id` is a `String` (e.g. `"PDF_XXXX"`), while `Passage.source_pdf_id` is an `Integer` FK to `source_pdfs.id`. *Observable effect*: passage creation via the pipeline needs this reconciliation before it can be exercised end-to-end.
- **Recreate-only DB migration (no Alembic).** Applying the schema requires deleting the local dev DB and re-running `create_tables()`; there is no incremental migration path. *Observable effect*: existing local data is lost on upgrade.
- **No per-item image cropping for labeled choice items.** Diagram/labeled-item image cropping for individual choice items is not implemented. *Observable effect*: an item's `image_path` stays null even when its `is_image` flag is true.


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

# Kiro 전달용 프롬프트 — 문제 이미지 영역 분해 + Claude Vision OCR/LaTeX 인식 + DB 스키마 재설계

아래 내용을 그대로 복사해서 Kiro에 붙여넣으면 됩니다. (Kiro가 spec 모드로 동작한다면 이 내용을 바탕으로 requirements/design/tasks를 먼저 생성하게 하세요.)

---

## 프로젝트 배경

`math-ai-graduation-project`는 FastAPI + SQLAlchemy(SQLite) 기반의 수능 수학 문제 처리 엔진입니다. 레이어 구조는 다음을 엄격히 따릅니다.

```
Router → Service → Repository → Model
              ↓
           Schema (Pydantic)
```

- Router(`app/routers/`): 요청/응답만 처리, Service에 위임
- Service(`app/services/`): 비즈니스 로직
- Repository(`app/repositories/`): DB 접근만 (모델당 1개)
- Schema(`app/schemas/`): Pydantic 검증/직렬화
- Model(`app/models/`): SQLAlchemy 테이블

**DB 관련 주의사항 (반드시 지킬 것)**
- `Base`는 `app/core/db_base.py`에 정의되어 있고 `app/core/database.py`가 re-export합니다. `Base` 정의를 옮기지 마세요 (reload 시 MetaData가 갈라져 FK가 깨지는 버그가 이미 한 번 발생했습니다).
- `create_tables()` (`app/core/database.py`)는 모델별 테이블을 **수동으로 나열**합니다. 새 모델을 추가하면 이 리스트에도 반드시 추가해야 합니다 (자동 인식 안 됨).
- 기본 DB는 `sqlite:///./math_problem_engine.db`.
- **`create_tables()`는 `Base.metadata.create_all()`이라 "없는 테이블만 새로 생성"하고 기존 테이블은 건드리지 않는다.** 새 테이블(`passages`, `problem_regions`, `problem_region_items`)은 자동으로 생기지만, 기존 `problems` 테이블에 `passage_id` 컬럼을 추가하는 건 이 방식으로 반영되지 않는다. `requirements.txt`에 `alembic==1.12.1`이 있지만 `alembic.ini`/`migrations/`가 없어 실제로는 초기화되어 있지 않다. 이번 작업에서는 (a) 로컬 개발 DB(`math_problem_engine.db`)를 삭제하고 `create_tables()`로 재생성하는 방식을 기본으로 하거나, (b) Alembic을 실제로 초기화해서 마이그레이션으로 관리하기 시작하거나 — 둘 중 하나를 명시적으로 선택해서 진행할 것. 후자를 택한다면 이번 스키마 변경분(신규 테이블 3개 + `problems.passage_id`)을 첫 마이그레이션으로 작성한다.
- SQLite는 기본적으로 FK 제약을 강제하지 않는다 (`PRAGMA foreign_keys=ON`이 지금 코드에 없음). region/item 테이블들이 참조 무결성(부모 삭제 시 자식 처리 등)에 의존한다면, `engine` 생성부(`_init_engine()`)에서 connect 시점에 이 PRAGMA를 켜는 것을 고려할 것. 강제하지 않기로 한다면 애플리케이션 레벨(Repository)에서 orphan 정리를 책임져야 한다.

## 현재 상태 — 스텁만 있고 실제 구현은 없음

아래 기능들은 **인터페이스와 목(mock) 반환값만 존재**하고, 실제 AI 모델 호출이 전혀 없는 상태입니다. Anthropic/Claude API 키를 읽는 코드도 없습니다.

1. `app/services/ocr_service.py` — `OCRServiceInterface.extract_text_from_image(image_data: bytes) -> str`, 항상 고정 문자열 반환
2. `app/services/latex_service.py` — `LaTeXServiceInterface.extract_latex_from_image(image_data: bytes) -> str`, 항상 고정 LaTeX 반환
3. `app/services/crop_classifier_service.py` — `CropClassifier`(ABC) / `MockCropClassifier`(좌표 기반 휴리스틱, 실사용 중) / `VisionLLMCropClassifier`(`raise NotImplementedError` 상태)
4. `app/core/config.py`의 `Settings`에는 `OPENAI_API_KEY`만 있고 Claude 키 관련 설정이 없음
5. `Problem` 모델(`app/models/problem.py`)은 문제 하나를 **통짜 이미지 + 통짜 텍스트 필드**로만 다룸. 한 문제 안에 지문/문제 텍스트/보기(선택지 또는 &lt;보기&gt; 박스)/도형 이미지가 섞여 있는 경우를 구조적으로 표현할 방법이 없음

## 왜 지금 구조(Problem 한 행 = JSON 필드 몇 개)로는 부족한가

지금은 `raw_text`, `raw_ocr_text`, `latex_text`, `problem_image_path` 처럼 문제 하나당 통짜 필드 몇 개에 다 밀어넣는 구조입니다. 그런데 실제 수능/모의고사 문제 한 개는 다음과 같이 **서로 다른 성격의 영역이 여러 개 섞여** 있습니다.

- **지문(passage)**: "다음 글을 읽고 물음에 답하시오" 류의 공통 지문 — 문제 여러 개가 지문 하나를 공유하기도 함 (예: 21~23번이 지문 하나를 공유)
- **문제 텍스트(question text)**: 실제 발문 ("...의 값을 구하시오" 등), 보통 텍스트 + 수식 혼합
- **&lt;보기&gt; 박스(statement box)**: ㄱ, ㄴ, ㄷ 형태로 명제를 나열하고 "옳은 것을 모두 고른 것은?" 식으로 묻는 경우. 선택지(①~⑤)와는 다른 영역입니다.
- **선택지(answer choices)**: ①~⑤ 5지선다
- **도형/그래프 이미지(diagram)**: 삼각형, 함수 그래프 등 — OCR 대상이 아니라 이미지 그대로 보존해야 하는 영역

이걸 문제 하나당 JSON 필드 몇 개로 뭉뚱그리면:
- 지문 공유가 안 됨 (문제마다 지문 텍스트가 중복 저장되고, 지문 하나를 고치면 N번 고쳐야 함)
- 선택지/보기 항목을 개별적으로 다루기 어려움 (채점, 문제 생성, 검수 UI에서 "3번 선택지만 수정"이 안 됨)
- 도형 이미지와 텍스트 영역이 뒤섞여서, 나중에 "이 문제에 그림이 몇 개 있는지", "그림만 모아서 보기" 같은 조회가 불가능
- 영역별로 신뢰도(confidence)나 개별 재-OCR 같은 걸 할 수 없음 (통짜 텍스트라 부분 재처리가 안 됨)

그래서 **관계형으로 정규화**해서, 문제 하나를 "영역(region)의 집합"으로 표현하는 게 맞습니다.

## 제안하는 DB 스키마

```
passages (지문 — 여러 문제가 공유 가능)
  id
  source_pdf_id       FK
  page_number
  passage_image_path
  crop_box            JSON {x,y,width,height}
  ocr_text
  latex_text
  created_at / updated_at

problems (기존 테이블 — passage_id 만 추가)
  ...기존 필드 유지...
  passage_id          FK -> passages.id, nullable

problem_regions (문제 하나에 속한 영역들)
  id
  problem_id          FK -> problems.id
  region_type         enum: QUESTION_TEXT / DIAGRAM / CHOICE_BOX / STATEMENT_BOX / TABLE / OTHER
  order_index         int   -- 읽는 순서(위→아래) 보존
  image_path          해당 영역만 크롭한 이미지 (텍스트 영역도 원본 대조용으로 저장 권장)
  bounding_box        JSON {x,y,width,height}  -- problem_image 기준 상대 좌표
  ocr_text            nullable
  latex_text          nullable  -- 텍스트/수식이 섞이면 수식 구간을 "$...$"로 감싼 혼합 텍스트로 저장
  confidence           float, nullable  -- vision 모델 자체 신뢰도
  created_at / updated_at

problem_region_items (선택지 ①~⑤ / 보기 ㄱㄴㄷ 처럼 "라벨 붙은 개별 항목")
  id
  region_id           FK -> problem_regions.id  (region_type이 CHOICE_BOX 또는 STATEMENT_BOX인 것에만 사용)
  label                문자열 ("①", "②"... 또는 "ㄱ", "ㄴ", "ㄷ"...)
  order_index
  text                 nullable
  latex                nullable
  image_path           선택지 자체가 그림인 경우 대비, nullable
  created_at / updated_at
```

**설계 의도**
- `passages`를 분리해서 지문 중복 저장/중복 OCR 호출을 피함 (지문 하나당 Claude Vision 호출 1회, 문제 N개가 재사용)
- `problem_regions`는 "이 문제 안에 어떤 영역이 몇 개, 어떤 순서로 있는지"를 관계형으로 표현 → 그림이 여러 개인 문제, 그림이 없는 문제 모두 자연스럽게 처리
- `problem_region_items`는 선택지/보기처럼 "라벨 붙은 리스트" 구조를 공통 테이블 하나로 처리 (선택지용 테이블, 보기용 테이블을 따로 만들지 않음 — 나중에 다른 라벨-리스트 유형이 생겨도 확장 가능)
- 기존 `Problem.raw_text` / `raw_ocr_text` / `latex_text` 필드는 삭제하지 말고, **region들을 합쳐 조립한 "최종본" 캐시**로 유지 (관리자 UI 목록/생성 파이프라인에서 매번 join 안 해도 되도록). Source of truth는 region 테이블들, 캐시는 problems 테이블.
- 지금 있는 `problem_image_path` / `page_image_path` / `crop_box`는 그대로 두고 "문제 전체 원본 크롭"으로 유지 (region들은 이 이미지를 다시 잘라낸 하위 영역).

## 구현해야 할 기능

### Feature A — 문제 이미지 → 영역 분해 → 유형별 Claude Vision 처리

`problem_image_path` 하나를 입력으로 받아, 한 번의 Claude Vision 호출(또는 필요시 2단계)로:

1. 이미지 안의 영역들을 감지하고 각각 `region_type`(QUESTION_TEXT / DIAGRAM / CHOICE_BOX / STATEMENT_BOX / TABLE / OTHER)과 bounding box로 분류
2. 텍스트성 영역(QUESTION_TEXT, CHOICE_BOX, STATEMENT_BOX, TABLE)은 OCR + LaTeX 혼합 텍스트까지 함께 추출 (한 번의 구조화 출력으로 region 감지와 OCR을 같이 받는 것을 권장 — 왕복 호출을 줄임)
3. DIAGRAM 영역은 OCR 하지 않고 bounding box만 받아서 이미지로 크롭 저장
4. CHOICE_BOX / STATEMENT_BOX로 분류된 영역은 내부 항목(①②③④⑤ 또는 ㄱㄴㄷ)까지 구조화해서 함께 추출

**요구사항 (EARS 형식)**
1. WHEN 문제 이미지가 주어지면, THEN 시스템은 Claude Vision API를 호출해 이미지 내 모든 영역(문제 텍스트/도형/선택지 박스/보기 박스 등)을 감지하고 각 영역의 유형과 bounding box를 반환해야 한다.
2. WHEN 감지된 영역이 텍스트성 영역(QUESTION_TEXT, CHOICE_BOX, STATEMENT_BOX, TABLE)이면, THEN 시스템은 해당 영역의 텍스트를 추출하고 수식 부분은 LaTeX로 변환하여 저장해야 한다.
3. WHEN 감지된 영역이 DIAGRAM이면, THEN 시스템은 OCR을 시도하지 않고 해당 영역을 원본 이미지에서 크롭하여 별도 파일로 저장해야 한다.
4. WHEN 영역이 CHOICE_BOX 또는 STATEMENT_BOX로 분류되면, THEN 시스템은 그 안의 개별 항목(①~⑤ 또는 ㄱ/ㄴ/ㄷ)을 순서를 보존한 채 `problem_region_items`로 구조화해서 저장해야 한다.
5. WHEN 지문(패시지)이 여러 문제에 걸쳐 반복되는 것으로 판단되면 (동일 `source_pdf_id` + `page_number` 범위에서 동일 지문 이미지가 재사용), THEN 시스템은 지문을 중복 OCR하지 않고 기존 `passages` 레코드를 재사용해야 한다. (최초 구현에서는 "같은 페이지·같은 지문 crop_box"로 단순 매칭해도 무방 — 완벽한 중복 감지는 향후 개선 과제로 남겨도 됨)
6. WHEN `ANTHROPIC_API_KEY`(또는 `CLAUDE_API_KEY`) 환경변수가 설정되어 있지 않으면, THEN 시스템은 예외로 전체 요청을 실패시키지 않고 안전하게 폴백해야 한다 (예: 기존 스텁 동작 유지).
7. WHEN Claude API 호출이 실패(타임아웃, 429, 5xx 등)하면, THEN 시스템은 에러를 로깅하고 상위 파이프라인(PDF import)이 전체적으로 실패하지 않도록 처리해야 한다.
8. 기존 `OCRServiceInterface`, `LaTeXServiceInterface`, `CropClassifier` 인터페이스는 유지하거나 하위 호환되게 확장한다. 새로 필요한 "영역 분해" 책임은 새 서비스(예: `ProblemRegionExtractionService`)로 분리하고, 기존 서비스들은 이 서비스를 내부에서 활용하거나 점진적으로 대체하는 방향으로 설계할 것 (기존 호출부를 깨지 않을 것).

### Feature B — DB 스키마 반영

위 "제안하는 DB 스키마" 섹션의 `passages` / `problem_regions` / `problem_region_items` 3개 모델을 추가하고, `problems.passage_id` FK를 추가한다.

**요구사항 (EARS 형식)**
1. WHEN 새 모델이 추가되면, THEN `app/core/database.py`의 `create_tables()` 리스트에도 반드시 추가되어야 한다 (자동 인식되지 않으므로).
2. WHEN region/아이템이 저장되면, THEN 각 이미지 경로는 기존 `uploads/problems/{source_pdf_id}/...` 저장 구조와 일관된 하위 경로 규칙을 따라야 한다 (예: `uploads/problems/{source_pdf_id}/{problem_id}/regions/{region_id}.png`).
3. WHEN `Problem` 응답 스키마(`app/schemas/problem_schema.py`)가 조회되면, THEN 클라이언트는 필요 시 하위 region/아이템 목록을 함께 받을 수 있어야 한다 (별도 확장 엔드포인트 `GET /api/problems/{id}/regions` 또는 응답에 nested 필드 포함 — 설계는 Kiro가 기존 라우팅 관례에 맞게 제안).
4. 기존 `problems` 테이블의 `raw_text`/`raw_ocr_text`/`latex_text` 필드는 삭제하지 않고, region들로부터 조립된 캐시로 계속 채워지도록 한다 (기존 API 응답 호환성 유지).

## 기술 제약사항

- **API**: Anthropic Claude API 공식 Python SDK(`anthropic`) 사용. `requirements.txt`에 추가.
- **키 관리**: `app/core/config.py`의 `Settings`에 `OPENAI_API_KEY`와 같은 패턴으로 `ANTHROPIC_API_KEY` property 추가. `.env`/`.env.example`에도 반영 (`.gitignore`에 이미 `.env`, `.env.*`는 제외 처리되어 있음).
- **모델 선택**: 비전 지원 Claude 모델(예: Claude Sonnet 계열의 최신 버전)을 사용하되, 모델명은 설정값으로 빼서 나중에 쉽게 바꿀 수 있게 할 것.
- **구조화 출력**: 영역 감지 + OCR + 항목 파싱을 가능한 한 하나의 Claude 호출에서 JSON 스키마로 한 번에 받도록 프롬프트를 설계할 것 (region마다 별도 API 호출을 하면 문제 1개당 호출 수가 과도하게 늘어남).
- **비용/안전장치**: 문제 이미지 1장당 기본 1회 호출, 재시도는 제한적으로(최대 1~2회). 무제한 재시도 금지.
- **기존 패턴 참고**: `app/prompts/`에 프롬프트 템플릿 파일이 분리된 구조(`problem_analysis_prompt.py` 등)를 따라, 새 프롬프트도 `app/prompts/`에 별도 파일로 분리. `app/services/prompt_builder_service.py` 스타일 참고.
- **건드리지 말 것**: `classification_service.py`, `generation_service.py`, `verification_service.py` 등 이번 범위 밖의 다른 스텁 서비스는 변경하지 않는다 (범위 최소화).
- **테스트**: 새 모델/서비스에 대한 단위 테스트를 `tests/`에 추가하고, Claude API 호출부는 목(mock)으로 대체해 실제 네트워크 호출 없이 테스트가 통과하도록 작성. 기존 테스트(`python -m pytest tests/ -v`, 현재 39개 통과)는 계속 통과해야 함.

## 완료 조건 체크리스트

- [ ] `ANTHROPIC_API_KEY` 환경변수를 읽는 설정이 추가됨
- [ ] `passages` / `problem_regions` / `problem_region_items` 모델이 추가되고 `create_tables()`에 반영됨
- [ ] `problems.passage_id` FK가 추가됨
- [ ] 문제 이미지 하나를 넣으면 영역(문제 텍스트/도형/선택지 박스/보기 박스)이 감지되어 `problem_regions`로 저장됨
- [ ] 도형(DIAGRAM) 영역은 OCR 없이 이미지로만 크롭 저장됨
- [ ] 텍스트성 영역은 OCR + LaTeX 혼합 텍스트로 저장됨
- [ ] 선택지(①~⑤)/보기(ㄱㄴㄷ) 항목이 `problem_region_items`로 순서 보존되어 저장됨
- [ ] 지문 공유 시 중복 OCR 없이 `passages` 레코드가 재사용됨 (최소 요건: 동일 crop_box 매칭)
- [ ] API 키 미설정/호출 실패 시에도 파이프라인이 죽지 않고 안전하게 폴백함
- [ ] 새 테스트가 추가되고, 기존 테스트를 포함해 전체 테스트가 통과함
- [ ] `CLAUDE.md`에 이번에 구현한 내용과 남은 한계를 반영해 업데이트함

# Math Problem Engine

AI 기반 수능 수학 문제 분석 및 유사문제 생성 시스템

## 프로젝트 목적

이 프로젝트는 수능 수학 문제를 분석하고, 풀이 전략 중심의 소유형 모듈을 기반으로 새로운 수학 문제를 생성하는 엔진입니다. 단순한 문제은행이 아닌, **풀이 전략과 공식 관계식을 중심으로 한 지능형 문제 생성 시스템**을 목표로 합니다.

## 전체 아키텍처 설명

```
math_problem_engine/
├── app/
│   ├── main.py              # FastAPI 애플리케이션 진입점
│   ├── core/                # 설정 및 데이터베이스
│   ├── models/              # SQLAlchemy 모델
│   ├── schemas/             # Pydantic 스키마
│   ├── services/            # 비즈니스 로직
│   ├── repositories/        # 데이터 접근 계층
│   ├── routers/             # API 엔드포인트
│   ├── prompts/             # AI 프롬프트 템플릿
│   └── utils/               # 유틸리티 함수
└── tests/                   # 테스트 코드
```

### 아키텍처 원칙

- **Router**: 요청/응답 처리만 담당
- **Service**: 비즈니스 로직 구현
- **Repository**: 데이터베이스 접근만 담당
- **Schema**: 데이터 검증 및 직렬화
- **Model**: 데이터베이스 테이블 정의

## 핵심 개념 설명

### 1. Problem (원본 문제)

사용자가 업로드한 원본 수학 문제를 저장합니다.

**주요 필드**:
- `title`: 문제 제목
- `source_type`: image, pdf, text, manual
- `raw_text`: 추출된 텍스트
- `latex_text`: LaTeX 수식
- `large_unit`: 큰 단원 (수학 I, 기하 등)
- `detected_module_ids`: 적용 가능한 소유형 모듈 ID들

### 2. ConceptModule (개념 모듈)

공식, 개념, 관계식을 저장합니다.

**예시**:
- 코사인 법칙: `c² = a² + b² - 2ab cos C`
- 삼각형 넓이 공식: `S = (1/2)ab sin C`

### 3. SolutionModule (소유형 모듈) ⭐ **가장 중요**

**소유형**은 단순 태그가 아니라 **작은 풀이 모듈**입니다. 문제를 해결하는 방향성과 전략을 담습니다.

**핵심 필드**:
- `trigger_conditions`: 이 유형을 적용해야 하는 조건들
- `core_concepts`: 필요한 핵심 개념들
- `solution_steps`: 풀이 단계들
- `can_combine_with`: 다른 유형과 결합 가능 여부
- `generation_rules`: 문제 생성 규칙

**예시**: 코사인 법칙 미지수 관계식 활용형
```json
{
  "module_id": "TRI_COSINE_RULE_RELATION",
  "name": "코사인 법칙 미지수 관계식 활용형",
  "trigger_conditions": [
    "삼각형에서 변과 각 사이의 관계가 필요하다",
    "코사인 법칙을 이용할 수 있다"
  ],
  "solution_steps": [
    "코사인 법칙으로 변과 각의 관계를 만들고",
    "부족한 미지수를 다른 조건으로 연결한다"
  ],
  "can_combine_with": ["TRIANGLE_AREA_FORMULA"]
}
```

### 4. TypeCombination (유형 조합)

여러 소유형이 어떻게 연결되는지 정의합니다.

**예시**: 코사인 법칙 + 삼각형 넓이 + 최대최소
- 코사인 법칙으로 관계식 생성
- 삼각형 넓이에 대입
- 범위 조건으로 최대최소 판단

### 5. GeneratedProblem (생성된 문제)

AI가 생성한 새로운 문제를 저장합니다.

## 실행 방법

### 1. 환경 설정

```bash
# 가상환경 생성 (선택사항)
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt
```

### 2. 애플리케이션 실행

```bash
uvicorn app.main:app --reload
```

### 3. API 문서 확인

브라우저에서 `http://localhost:8000/docs` 접속하여 Swagger UI 확인

## API 목록

### 저장된 PDF를 A안(번호 기반 crop)으로 재처리

`POST /api/pdf-import/source-pdfs/{source_pdf_id}/reprocess`

저장된 원본 PDF를 다시 읽어 새 `source_pdf_id` 아래에 페이지와 문제 이미지를 생성합니다. 원본 문제와 영역은 유지됩니다. 응답의 `reprocessed_from_source_pdf_id`가 원본, `source_pdf_id`가 새 결과입니다. `numbered_problem_count`로 번호가 저장된 문제 수를 확인하고, `GET /api/pdf-import/source-pdfs/{새 source_pdf_id}/problems`에서 결과를 검토할 수 있습니다.

기본값 `crop_mode=a_only`는 번호 기반 crop을 다시 실행합니다. 새 문제에는 `full_problem` 영역만 자동 생성되며, 문제 내부의 Vision 영역 추출은 실행하지 않습니다.

`crop_mode=auto`는 각 페이지 이미지와 A안의 절취선을 Gemini에 요청해 검토합니다. A안이 정확하면 유지하고, 누락 또는 잘못된 절취선이 있으면 Gemini가 페이지의 모든 문제 박스를 다시 제안합니다. B안 박스는 좌표, 크기, 겹침, 번호 중복을 검사한 뒤 저장합니다. Gemini 요청 실패, 불확실한 판단, 잘못된 박스가 나오면 기존 번호/이미지 방식으로 저장하되 해당 페이지와 새 PDF 상태를 `needs_review`로 표시합니다. 응답의 `page_reports`에 페이지별 방식, 검토 필요 여부, 이유, 사용 토큰, 실제 저장 수가 포함됩니다. 원본 PDF와 기존 문제 데이터는 유지됩니다. `auto`에는 `.env`의 `GEMINI_API_KEY`가 필요하며 페이지당 한 요청을 기준으로 호출 비용이 발생합니다(일시적 요청 실패 시 1회 재시도).

```bash
curl -X POST "http://localhost:8000/api/pdf-import/source-pdfs/PDF_B0A98A13/reprocess"

# 페이지별 Gemini 검토 + 필요 시 B안 재탐지
curl -X POST "http://localhost:8000/api/pdf-import/source-pdfs/PDF_B0A98A13/reprocess?crop_mode=auto"
```

여백 중심 후보 생성과 사용자 채택·버리기 UI의 구현 상태는 [crop 검토 UI 계획](docs/CROP_REVIEW_UI_PLAN.md), 바깥 crop과 문제 내부 region crop 설명은 [crop 파이프라인 보고서](docs/CROP_PIPELINE_REPORT.md)에 있습니다.

새 검토 경로: 서버 실행 후 `/admin` → **PDF 업로드**에서 파일을 올리면 원본 페이지와 조절 가능한 crop 박스가 바로 열리고, 모든 페이지의 후보가 순서대로 생성됩니다. 기존 박스를 끌거나 모서리를 조절하고, 빈 곳을 드래그해 누락된 영역을 추가할 수 있습니다. 오른쪽의 **버리기**는 선택한 후보만 제외하고, **채택하기**는 선택 영역을 저장한 뒤 해당 페이지의 남은 후보를 한 번에 채택합니다. 별도 페이지 확인 버튼은 없습니다. 모든 페이지를 채택한 뒤 **검토 완료 · 문제함에 등록**을 누르면 채택한 crop만 문제함에 저장됩니다. Gemini는 `GEMINI_API_KEY`가 있을 때 페이지 전체와 여백 후보를 검토합니다. 기존 즉시 처리 API `POST /api/pdf-import/upload`는 계속 사용할 수 있습니다.

### Problem API
- `POST /problems` - 문제 등록
- `GET /problems` - 전체 문제 목록
- `GET /problems/{id}` - 특정 문제 조회
- `POST /problems/{id}/analyze` - 문제 분석 실행

### SolutionModule API
- `POST /solution-modules` - 자연어 설명으로 모듈 생성
- `GET /solution-modules` - 전체 모듈 목록
- `GET /solution-modules/{id}` - 특정 모듈 조회
- `PATCH /solution-modules/{id}/verify` - 모듈 검증

### Generation API
- `POST /generate/problem` - 새로운 문제 생성

### 기타 API
- ConceptModule, TypeCombination CRUD API

## 예시 API 요청

### 문제 등록
```bash
curl -X POST "http://localhost:8000/problems/" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "코사인 법칙 문제",
    "source_type": "text",
    "raw_text": "삼각형 ABC에서 AB=5, BC=6, ∠ABC=60° 일 때 AC를 구하시오."
  }'
```

### 문제 분석
```bash
curl -X POST "http://localhost:8000/problems/1/analyze"
```

### 소유형 모듈 생성
```bash
curl -X POST "http://localhost:8000/solution-modules/" \
  -H "Content-Type: application/json" \
  -d '"코사인 법칙을 사용해서 변의 길이를 구하는 유형"'
```

### 문제 생성
```bash
curl -X POST "http://localhost:8000/generate/problem" \
  -H "Content-Type: application/json" \
  -d '{
    "selected_module_ids": ["TRI_COSINE_RULE_RELATION"],
    "generation_goal": "삼각형 변의 길이 구하기"
  }'
```

## 향후 확장 계획

### 1. OCR 연동
- Tesseract 또는 Google Vision API로 이미지 텍스트 추출
- 수식 인식 정확도 향상

### 2. LaTeX 인식 연동
- MathPix API로 이미지에서 LaTeX 변환
- 수식 파싱 및 검증

### 3. LLM API 연동
- OpenAI GPT-4로 실제 프롬프트 실행
- 더 정확한 문제 분석 및 생성

### 4. SymPy 검증
- 생성된 문제의 수학적 타당성 검증
- 답안 자동 계산 및 검증

### 5. 문제 난이도 조절
- 난이도 점수화 알고리즘 개발
- 사용자 레벨에 맞는 문제 생성

### 6. 수능 기출 라벨링
- 실제 수능 문제 데이터 수집
- 정확도 향상을 위한 학습 데이터 구축

### 7. 사용자 오답 기반 추천
- 학생의 오답 패턴 분석
- 개인 맞춤 문제 생성

## 새로 추가된 기능: PDF 문제지 업로드 및 후보 추출

사용자가 PDF 문제지를 업로드하면 서버는 다음 흐름을 수행합니다.

1. 원본 PDF를 저장합니다.
2. PDF 페이지를 이미지로 렌더링합니다.
3. 페이지 이미지에서 문제 후보 영역을 heuristic 방식으로 잘라냅니다.
4. 각 후보 이미지를 저장합니다.
5. 문제 후보를 Problem 테이블에 저장하고 기본 상태를 `unclassified`로 둡니다.

이 단계에서는 OCR, LaTeX 인식, 자동 분류, 정답/해설 생성은 구현하지 않습니다.

## 실행 방법

### 1. 환경 설정

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\\Scripts\\activate
pip install -r requirements.txt
```

### 2. 애플리케이션 실행

```bash
uvicorn app.main:app --reload
```

### 3. API 문서 확인

브라우저에서 `http://localhost:8000/docs` 에 접속해 Swagger UI를 확인합니다.

## API 목록

### PDF Import API
- `POST /api/pdf-import/upload` - PDF 업로드 및 후보 추출 (PyMuPDF 문제 번호 자동 감지)
- `GET /api/pdf-import/source-pdfs` - 업로드된 PDF 목록 조회
- `GET /api/pdf-import/source-pdfs/{source_pdf_id}/problems` - 특정 PDF에서 추출된 문제 목록 조회

### Problem API
- `GET /api/problems` - 미분류 문제 목록 조회
- `GET /api/problems/{problem_id}` - 문제 상세 조회
- `PATCH /api/problems/{problem_id}` - 문제 정보 수정
- `DELETE /api/problems/{problem_id}` - 상태를 `excluded`로 변경

## 예시 API 요청

### PDF 업로드
```bash
curl -X POST "http://localhost:8000/api/pdf-import/upload" \
  -F "file=@sample.pdf"
```

**응답 예시**:
```json
{
  "source_pdf_id": "PDF_A1B2C3D4",
  "total_pages": 20,
  "imported_problem_count": 40,
  "status": "imported"
}
```

각 페이지의 문제는 자동으로 감지되며, `problem_number` 필드에 인식된 문제 번호가 저장됩니다.

### 미분류 문제 조회
```bash
curl "http://localhost:8000/api/problems?status=unclassified&page=1&page_size=20"
```

**응답 예시**:
```json
[
  {
    "problem_id": 1,
    "problem_number": 1,
    "source_pdf_id": "PDF_A1B2C3D4",
    "page_number": 1,
    "elective_subject": "common",
    "status": "unclassified",
    "problem_image_url": "/uploads/problems/PDF_A1B2C3D4/P_000001.png",
    "page_image_url": "/uploads/pages/PDF_A1B2C3D4/page_001.png",
    ...
  }
]
```

### 문제 수정
```bash
curl -X PATCH "http://localhost:8000/api/problems/1" \
  -H "Content-Type: application/json" \
  -d '{
    "problem_number": 10,
    "large_unit": "수학 I",
    "middle_unit": "삼각함수",
    "difficulty": "medium",
    "score": 4,
    "tags": ["그래프", "삼각함수"],
    "memo": "그래프와 직선의 교점 구조",
    "status": "classified"
  }'
```

## PDF 임포트 워크플로우

### 문제 번호 감지 (자동)

PDF 업로드 시 다음 단계를 자동으로 수행합니다:

1. **PDF 페이지 렌더링**: 각 페이지를 이미지로 변환
2. **문제 번호 감지**: PyMuPDF의 텍스트 좌표 추출 활용
   - "1.", "2.", ..., "30." 패턴 인식
   - 선택지 번호(①, ②) 등은 제외
   - 페이지 상단과 하단 텍스트(타이틀, 페이지 번호) 제외
3. **컬럼 감지**: x 좌표로 left/right 컬럼 구분
4. **문제 영역 추출**: 
   - 문제 번호가 감지되면, 그 위치를 기준으로 정확한 crop box 생성
   - 2개 미만 감지되면 fallback 휴리스틱 사용 (2단 또는 3단 레이아웃)
5. **이미지 저장**: 크롭된 문제 이미지 저장
6. **DB 저장**: Problem 레코드 생성 (problem_number 필드에 감지된 번호 기록)

**Fallback 동작**: PyMuPDF 미사용 환경에서는 기존 휴리스틱 방식 사용

## 데이터 저장 구조

- 원본 PDF는 `uploads/pdfs/{source_pdf_id}.pdf` 에 저장됩니다.
- 페이지 이미지는 `uploads/pages/{source_pdf_id}/page_001.png` 형태로 저장됩니다.
- 문제 후보 이미지는 `uploads/problems/{source_pdf_id}/P_000001.png` 형태로 저장됩니다.

## 현재 한계

- OCR 없음
- 문제 번호 자동 인식 불완전
- 번호를 읽지 못한 페이지의 기본 crop은 휴리스틱 기반 (`crop_mode=auto` 재처리에서 Gemini 검토 가능)
- 자동 유형 분류 없음
- LaTeX 인식 없음

## 다음 단계

- crop 영역 수동 수정 UI
- OCR 추가
- LaTeX 인식 추가
- 소유형 분류 관리
- 학습지 생성 PDF 출력
- LLM 기반 단원/소유형 추천

## 개발 원칙

- **확장성**: 모든 AI 기능은 인터페이스로 분리되어 교체 가능
- **모듈성**: 각 컴포넌트가 독립적으로 테스트 및 교체 가능
- **타입 안전성**: 모든 함수에 타입 힌트 적용
- **테스트 우선**: 새로운 기능 추가 시 테스트 코드 작성

이 시스템은 단순한 문제 생성기를 넘어, **수학 교육의 패러다임을 바꾸는 도구**가 될 것입니다.

## 마이그레이션 노트: ProblemRegion 좌표 컬럼

`ProblemRegion` 에 좌표 승격 컬럼(`x1, y1, x2, y2, page_width, page_height, parent_region_id`)이
추가되었습니다. 이와 관련한 스키마 갱신 방법은 아래와 같습니다.

- **`create_all()` 은 기존 테이블에 컬럼을 추가하지 않습니다.** SQLAlchemy 의
  `Base.metadata.create_all()` 은 존재하지 않는 테이블만 새로 만들고, 이미 존재하는
  테이블의 컬럼 변경/추가는 수행하지 않습니다. 따라서 기존 DB 파일을 그대로 두면
  새 컬럼이 반영되지 않습니다.

- **개발 환경(데이터 보존 불필요)**: `math_problem_engine.db` 파일을 삭제한 뒤 앱을
  다시 실행(또는 테이블 재생성)하면 새 스키마로 재생성됩니다.

  ```bash
  # 예: 개발 DB 초기화
  del math_problem_engine.db   # Windows
  # rm math_problem_engine.db  # macOS/Linux
  ```

- **운영/보존 데이터**: 기존 데이터를 유지해야 하는 경우 아래 마이그레이션 스크립트를
  실행하면 `ALTER TABLE` 로 7개 컬럼을 idempotent 하게 추가합니다(이미 있으면 건너뜀).

  ```bash
  python scripts/migrate_add_region_coords.py
  ```

  대상 DB 는 `DATABASE_URL` 환경변수(sqlite URL)를 우선 사용하며, 없으면 기본값
  `sqlite:///./math_problem_engine.db` 를 사용합니다.

## 겹침 검증 훅 플래그: ENABLE_REGION_OVERLAP_VALIDATION

crop/region 파이프라인에 "영역 좌표 겹침 검증" 루프를 복원하는 훅이 추가되었습니다.
이 훅은 **환경변수 `ENABLE_REGION_OVERLAP_VALIDATION` 로 gating** 되며 **기본값은 `False`**
(비활성)입니다.

- **off (기본)**: 기존 crop 파이프라인과 **100% 동일**하게 동작합니다. 검증기를
  호출조차 하지 않으므로 기존 crop 결과에 회귀가 없습니다.
- **on (`ENABLE_REGION_OVERLAP_VALIDATION=true`)**: 두 지점에서 겹침 검증기
  (`region_overlap_validator.validate_and_resolve`)를 적용합니다.
  1. **crop 후보 단계**(`mode="candidates"`): merge 직후 후보 crop_box 들을 corner 로
     변환해 과검출·과병합 겹침을 보정(작은 쪽 reject)한 뒤 다시 xywh 로 되돌려 저장.
  2. **region 추출 단계**(`mode="regions"`): 문제별 `ProblemRegion` 좌표를 조회해
     겹침을 보정(shrink/clamp/부모-자식)한 뒤 `x1..y2` 컬럼과 `bounding_box` JSON 에
     동시 기록.

두 훅 모두 **fail-open** 입니다. 보정 중 예외가 발생하면 원본 좌표를 그대로 유지하고
warning 로그만 남기며, PDF 임포트 파이프라인을 중단시키지 않습니다.

```bash
# 훅 활성화 예시 (Windows PowerShell)
$env:ENABLE_REGION_OVERLAP_VALIDATION = "true"
uvicorn app.main:app --reload
```

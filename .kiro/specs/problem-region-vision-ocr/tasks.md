# Implementation Plan: problem-region-vision-ocr

## Overview

이 구현 계획은 하나의 문제 이미지를 타입이 구분된 영역(region)들의 정렬된 집합으로 분해하고, 각 영역의 OCR·LaTeX 텍스트와 라벨 항목을 추출해 새 관계형 스키마(`passages`, `problem_regions`, `problem_region_items`, `problems.passage_id`)에 저장하는 기능을 점진적으로 구현한다. 언어는 기존 코드베이스와 동일한 **Python**이며, 계층 구조(Router → Service → Repository → Model + Pydantic Schema)를 그대로 준수한다.

작업 순서는 서로 위에 쌓이도록 구성했다: 설정/의존성 → 모델 + 스키마 재생성 → 리포지토리 → 프롬프트 + `ClaudeVisionClient` → `ProblemRegionExtractionService` → 스토리지 헬퍼 → Pydantic 스키마 + 라우터 → PDF 임포트 통합 → 테스트(단위 + PBT) → 문서. 각 단계는 이전 단계의 산출물을 사용하며, 마지막에 모든 조각이 파이프라인에 연결된다.

`*`로 표시된 하위 작업은 테스트 관련(단위/속성/통합)으로 선택 사항이며 MVP에서 건너뛸 수 있다. 핵심 구현 작업은 선택 표시가 없다.

## Tasks

- [x] 1. 설정과 의존성 준비
  - [x] 1.1 `app/core/config.py`에 Claude 설정 프로퍼티 추가
    - 기존 `@property` 패턴을 따라 `ANTHROPIC_API_KEY` 프로퍼티 추가: `os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")`로 폴백 순서 구현, 둘 다 없으면 `None` 반환
    - `CLAUDE_VISION_MODEL` 프로퍼티 추가: `os.getenv("CLAUDE_VISION_MODEL", "claude-3-5-sonnet-latest")` 형태로 비전 지원 기본 모델명 반환
    - _Requirements: 13.1, 13.2, 13.3, 6.2, 6.3_

  - [x] 1.2 `requirements.txt`에 `anthropic` 의존성 고정 버전으로 추가
    - 정확 버전 또는 최소 버전 지정자(unbounded 금지)로 `anthropic` 항목 추가
    - _Requirements: 13.5_

  - [x] 1.3 `.env.example`에 Claude 자격증명 변수 문서화
    - `ANTHROPIC_API_KEY`와 선택적 `CLAUDE_API_KEY`를 플레이스홀더 값으로 추가(실제 자격증명 금지)
    - _Requirements: 13.6_

  - [ ]* 1.4 설정 프로퍼티 단위/예시 테스트 작성
    - `ANTHROPIC_API_KEY`만 설정 시 그 값 사용, `CLAUDE_API_KEY`만 설정 시 폴백, 둘 다 설정 시 `ANTHROPIC_API_KEY` 우선, 둘 다 미설정 시 `None` 확인 (자격증명 우선순위 예시 테스트)
    - `CLAUDE_VISION_MODEL` 기본값과 환경변수 오버라이드 확인
    - _Requirements: 6.2, 6.3, 13.1, 13.2, 13.3_

- [x] 2. 신규 영속 모델 정의
  - [x] 2.1 `app/models/passage.py`에 `Passage` 모델 정의
    - `from app.core.database import Base`로 Base 가져오기 (Base는 `db_base.py`에서 이동 금지)
    - 필드: `id`(PK), `source_pdf_id`(FK→`source_pdfs.id`, nullable=False), `page_number`(nullable=False), `passage_image_path`(nullable=False), `crop_box`(JSON, nullable=True), `ocr_text`(Text, nullable=True), `latex_text`(Text, nullable=True), `created_at`, `updated_at`
    - _Requirements: 9.1, 9.2, 9.8_

  - [x] 2.2 `app/models/problem_region.py`에 `RegionType` enum과 `ProblemRegion` 모델 정의
    - `RegionType(str, enum.Enum)`: `QUESTION_TEXT`, `DIAGRAM`, `CHOICE_BOX`, `STATEMENT_BOX`, `TABLE`, `OTHER`
    - `ProblemRegion(Base)`: `id`(PK), `problem_id`(FK→`problems.id`, nullable=False), `region_type`(String, nullable=False, `.value` 저장), `order_index`(Integer, nullable=False), `image_path`(String, nullable=True), `bounding_box`(JSON, nullable=False), `ocr_text`(Text, nullable=True), `latex_text`(Text, nullable=True), `confidence`(Float, nullable=True), `created_at`, `updated_at`
    - _Requirements: 9.3, 9.8_

  - [x] 2.3 `app/models/problem_region_item.py`에 `ProblemRegionItem` 모델 정의
    - 필드: `id`(PK), `region_id`(FK→`problem_regions.id`, nullable=False), `label`(String, nullable=False), `order_index`(Integer, nullable=False), `text`(Text, nullable=True), `latex`(Text, nullable=True), `image_path`(String, nullable=True), `created_at`, `updated_at`
    - _Requirements: 9.4, 9.8_

  - [x] 2.4 `app/models/problem.py`에 `passage_id` 외래키 추가
    - `passage_id = Column(Integer, ForeignKey("passages.id"), nullable=True, index=True)` 추가, 기존 필드·프로퍼티는 변경하지 않음
    - _Requirements: 9.5, 11.1_

  - [ ]* 2.5 신규 모델 필드 제약 단위 테스트 작성
    - `passages`에 `id`/`source_pdf_id`/`page_number`/`passage_image_path` 중 하나라도 null로 삽입 시 `IntegrityError` 발생, `crop_box`/`ocr_text`/`latex_text` null 허용 확인 (예시 기반 테스트)
    - _Requirements: 9.2_

- [x] 3. 데이터베이스 등록 및 FK 무결성 설정
  - [x] 3.1 `create_tables()`에 신규 모델 등록
    - `app/core/database.py`의 `create_tables()`에 `Passage`, `ProblemRegion`, `ProblemRegionItem` import 후 `tables=[...]` 목록에 세 `__table__` 추가
    - 세 테이블 중 하나라도 생성 실패 시 작업을 중단하고 실패 테이블을 식별하는 오류를 내며 부분 생성 상태를 남기지 않도록 처리
    - _Requirements: 9.6, 9.7_

  - [x] 3.2 `_init_engine()`에 SQLite `PRAGMA foreign_keys=ON` connect 이벤트 등록
    - `sqlite` URL일 때만 SQLAlchemy `event.listens_for(engine, "connect")`로 연결마다 `PRAGMA foreign_keys=ON` 실행
    - _Requirements: 9.8_

  - [x] 3.3 로컬 개발 DB 재생성 (파괴적, 로컬 전용)
    - 기존 로컬 `math_problem_engine.db`를 삭제한 뒤 `create_tables()`를 재실행해 신규 세 테이블과 `problems.passage_id` 컬럼 반영
    - 이 단계는 로컬 개발 데이터 소실을 유발하는 파괴적 작업임을 명시하며 운영 데이터에는 적용하지 않음. 적용 후 기존 `problems` 행의 `passage_id`는 모두 null
    - _Requirements: 9.9_

  - [ ]* 3.4 스키마 생성 스모크 테스트 작성
    - 인메모리 또는 임시 SQLite에서 `create_tables()` 호출 후 `passages`, `problem_regions`, `problem_region_items` 테이블이 생성되었는지 확인 (스모크 테스트 1회)
    - _Requirements: 9.6, 9.7_

- [x] 4. 신규 리포지토리 구현
  - [x] 4.1 `app/repositories/passage_repository.py`에 `PassageRepository` 구현
    - 생성자에서 `Session` 주입, 기존 `ProblemRepository` 스타일 준수
    - `find_matching(source_pdf_id, page_number, crop_box)`: 같은 `source_pdf_id`·`page_number`이고 `crop_box` 네 좌표(left, top, right, bottom)가 각각 5px 이내로 일치하는 기존 지문 탐색 (필요충분: 하나라도 5px 초과 시 비매칭)
    - `create(passage_data)`
    - _Requirements: 5.1, 5.3, 5.6_

  - [ ]* 4.2 `PassageRepository.find_matching` 속성 기반 테스트 작성
    - **Property 9: 지문 매칭은 5픽셀 허용오차 규칙을 정확히 따른다**
    - **Validates: Requirements 5.1**
    - `# Feature: problem-region-vision-ocr, Property 9: 지문 매칭은 5픽셀 허용오차 규칙을 정확히 따른다` 태그, Hypothesis `@settings(max_examples=100)` 이상

  - [x] 4.3 `app/repositories/problem_region_repository.py`에 `ProblemRegionRepository` 구현
    - `create(region_data)`, `get_by_problem_id(problem_id)`(order_index 오름차순 반환), `delete_by_problem_id(problem_id)`(재추출 시 기존 영역 정리)
    - _Requirements: 12.1_

  - [x] 4.4 `app/repositories/problem_region_item_repository.py`에 `ProblemRegionItemRepository` 구현
    - `create(item_data)`, `get_by_region_id(region_id)`(order_index 오름차순 반환)
    - _Requirements: 12.1_

- [-] 5. Checkpoint - 모델·리포지토리·스키마 검증
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. 스토리지 헬퍼 확장
  - [x] 6.1 `app/core/storage.py`에 영역/항목 이미지 경로 헬퍼 추가
    - `get_region_image_path(source_pdf_id, problem_id, region_id)` → `uploads/problems/{source_pdf_id}/{problem_id}/regions/{region_id}.png`
    - `get_item_image_path(source_pdf_id, problem_id, item_id)` → `uploads/problems/{source_pdf_id}/{problem_id}/items/{item_id}.png`
    - 식별자가 비어 있으면 파일을 쓰지 않고 누락 식별자 오류 반환, 대상 경로에 파일이 이미 있으면 덮어써 최신 이미지만 유지
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [ ]* 6.2 이미지 경로 규칙 속성 기반 테스트 작성
    - **Property 12: 이미지 저장 경로는 규칙 패턴을 따른다**
    - **Validates: Requirements 10.1, 10.2**
    - `# Feature: problem-region-vision-ocr, Property 12: 이미지 저장 경로는 규칙 패턴을 따른다` 태그, `@settings(max_examples=100)` 이상

  - [ ]* 6.3 이미지 경로 식별자 누락 예시 테스트 작성
    - 식별자 누락/빈 값 시 파일 미기록 및 오류 반환, 기존 파일 덮어쓰기 확인 (예시/엣지 테스트)
    - _Requirements: 10.3, 10.4_

- [x] 7. Claude Vision 프롬프트 및 클라이언트 구현
  - [x] 7.1 `app/prompts/region_extraction_prompt.py`에 프롬프트 빌더 추가
    - 기존 프롬프트 모듈 스타일(문자열 반환 함수)로 `build_region_extraction_prompt()` 구현
    - 단일 구조화 JSON 출력 지시: 영역 배열(각 `region_type`, `bounding_box{left, top, right, bottom}`, `ocr_text`, `latex_text`, `confidence`)과 CHOICE_BOX/STATEMENT_BOX의 라벨 항목 배열(`label`, `text`, `latex`, `is_image`) 포함
    - _Requirements: 14.3, 14.1_

  - [x] 7.2 `app/services/claude_vision_client.py`에 `ClaudeVisionClient`와 `VisionCallResult` 구현
    - `VisionCallResult` 데이터클래스: `success`, `raw_json`, `failure_type`("timeout"|"rate_limited"|"server_error"|"malformed"|None), `error_message`
    - `is_configured()`: 자격증명 존재 여부 반환
    - `extract(image_path, prompt)`: 공식 `anthropic` SDK를 감싸는 단일 구조화 호출, 60초 타임아웃, 정상 시 이미지당 호출 1회, 응답 파싱 불가 시 `failure_type="malformed"`
    - timeout/429/5xx 실패 시 실패 유형+이미지 ID 로그 후 최대 2회 재시도, 매 재시도 전 1초 이상 30초 이하 대기(백오프)
    - 자격증명 없으면 외부 서비스로 요청 전송하지 않고 미설정 오류 반환
    - _Requirements: 7.1, 7.2, 7.5, 13.4, 14.1, 14.2, 14.6_

  - [ ]* 7.3 재시도 상한·백오프 속성 기반 테스트 작성 (SDK 목킹)
    - **Property 11: 재시도는 상한과 백오프 범위를 지킨다**
    - **Validates: Requirements 7.2**
    - `# Feature: problem-region-vision-ocr, Property 11: 재시도는 상한과 백오프 범위를 지킨다` 태그, `@settings(max_examples=100)` 이상, 총 호출 ≤ 3회 및 대기 1~30초 검증

  - [ ]* 7.4 `ClaudeVisionClient` 실패 유형별 예시 테스트 작성 (SDK 목킹)
    - timeout/429/5xx별 로깅과 `failure_type` 매핑, malformed 응답 시 `failure_type="malformed"`, 자격증명 미설정 시 전송 없이 오류 반환 확인
    - _Requirements: 7.1, 13.4, 14.5, 14.6_

- [x] 8. 영역 추출 오케스트레이션 서비스 구현
  - [x] 8.1 `ProblemRegionExtractionService` 골격과 이미지 검증·자격증명 폴백 구현
    - `app/services/problem_region_extraction_service.py`에 서비스 생성자(리포지토리 주입, `vision_client` 주입 가능) 및 `RegionExtractionResult`(성공 여부, 생성 영역 수, 영역 단위 오류 목록) 정의
    - 이미지 읽기 불가 시 오류 결과 반환·영역 미생성
    - 자격증명 부재 시 기존 스텁 동작으로 폴백해 성공 반환하고 warning 로그 1회 발생
    - _Requirements: 1.2, 6.1, 6.4, 8.1_

  - [x] 8.2 단일 Vision 호출 및 JSON 구조 검증·영역 타입/정렬 구현
    - 단일 `ClaudeVisionClient.extract()` 호출로 영역 탐지·텍스트/LaTeX·라벨 항목을 함께 획득
    - malformed JSON 시 로그 후 부분 저장 없이 실패 반환, 60초 미응답 시 중단·부분 저장 없음
    - 각 영역에 집합 {QUESTION_TEXT, DIAGRAM, CHOICE_BOX, STATEMENT_BOX, TABLE, OTHER} 중 정확히 하나의 `region_type` 부여
    - 바운딩 박스(left, top, right, bottom) 기록, top 오름차순·동일 시 left 오름차순 정렬로 0-기반 연속·유일한 `order_index` 부여
    - 영역이 없으면 빈 컬렉션을 오류 없이 반환
    - _Requirements: 1.1, 1.4, 1.5, 1.6, 1.7, 1.8, 14.1, 14.2, 14.5, 14.6_

  - [ ]* 8.3 영역 Region_Type 속성 기반 테스트 작성
    - **Property 1: 모든 영역은 유효한 Region_Type을 갖는다**
    - **Validates: Requirements 1.4**
    - `# Feature: problem-region-vision-ocr, Property 1: 모든 영역은 유효한 Region_Type을 갖는다` 태그, `@settings(max_examples=100)` 이상

  - [ ]* 8.4 영역 order_index 정렬 속성 기반 테스트 작성
    - **Property 2: 영역 order_index는 (top, left) 정렬로 0-기반 연속·유일이다**
    - **Validates: Requirements 1.6, 1.7**
    - `# Feature: problem-region-vision-ocr, Property 2: 영역 order_index는 (top, left) 정렬로 0-기반 연속·유일이다` 태그, `@settings(max_examples=100)` 이상

  - [x] 8.5 텍스트 영역 OCR/LaTeX 반영 및 confidence 저장 구현
    - Text_Region의 `ocr_text` 저장, 수식 포함 시 `$...$`로 감싼 혼합 텍스트를 `latex_text`에 저장, 수식 없으면 구분자 없이 평문 저장
    - confidence 반환 시 0.0~1.0으로 제약해 저장, 미반환 시 null
    - 텍스트 추출 실패/빈 결과 시 해당 영역 `ocr_text`·`latex_text` null 유지, 오류 표시 생성, 나머지 영역 처리 계속
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [ ]* 8.6 confidence 범위 속성 기반 테스트 작성
    - **Property 3: confidence는 항상 null이거나 0.0~1.0 범위 내이다**
    - **Validates: Requirements 2.4, 2.5**
    - `# Feature: problem-region-vision-ocr, Property 3: confidence는 항상 null이거나 0.0~1.0 범위 내이다` 태그, `@settings(max_examples=100)` 이상

  - [ ]* 8.7 텍스트 영역 처리·실패 격리 속성 기반 테스트 작성
    - **Property 4: 텍스트 영역은 OCR을 시도하고 실패는 격리된다**
    - **Validates: Requirements 2.1, 2.6**
    - `# Feature: problem-region-vision-ocr, Property 4: 텍스트 영역은 OCR을 시도하고 실패는 격리된다` 태그, `@settings(max_examples=100)` 이상

  - [x] 8.8 다이어그램 영역 크롭·바운딩 박스 클램핑 구현
    - Diagram_Region은 OCR/LaTeX 생략하고 원본 이미지에서 바운딩 박스로 크롭해 별도 파일 저장, 저장 경로를 `image_path`에 기록
    - 박스가 이미지 경계를 넘으면 경계로 클램프, 클램프 후 폭/높이 1px 미만 또는 면적 0 이하이면 크롭 생략·`image_path` 빈값·오류 표시
    - 크롭 저장 실패 시 `image_path` 빈값·오류 표시, 나머지 영역 계속
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [ ]* 8.9 다이어그램 텍스트 부재 속성 기반 테스트 작성
    - **Property 5: 다이어그램 영역은 OCR/LaTeX 텍스트를 갖지 않는다**
    - **Validates: Requirements 3.1**
    - `# Feature: problem-region-vision-ocr, Property 5: 다이어그램 영역은 OCR/LaTeX 텍스트를 갖지 않는다` 태그, `@settings(max_examples=100)` 이상

  - [ ]* 8.10 바운딩 박스 클램프 속성 기반 테스트 작성
    - **Property 6: 바운딩 박스 클램프는 항상 경계 내이거나 무효 판정이다**
    - **Validates: Requirements 3.4, 3.5**
    - `# Feature: problem-region-vision-ocr, Property 6: 바운딩 박스 클램프는 항상 경계 내이거나 무효 판정이다` 태그, `@settings(max_examples=100)` 이상

  - [x] 8.11 라벨 항목 구조화 구현
    - CHOICE_BOX/STATEMENT_BOX의 내부 항목을 각각 Labeled_Item으로 분리(영역당 1~10개 지원), 라벨을 원문 그대로 보존("①"~"⑤", "ㄱ"/"ㄴ"/"ㄷ")
    - 읽기 순서(위→아래, 그다음 좌→우)로 0-기반 연속·유일 `order_index` 부여
    - 텍스트 항목은 `text`(+수식 시 `latex`) 저장, 수식 없으면 `latex` 빈값, 이미지 항목은 `image_path`만 채우고 `text`·`latex` 빈값
    - 라벨 미검출 시 항목 미생성·오류 표시, 원본 영역 레코드 보존
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

  - [ ]* 8.12 라벨 항목 개수·라벨 보존 속성 기반 테스트 작성
    - **Property 7: 라벨 항목은 개수가 보존되고 라벨이 원문 그대로 유지된다**
    - **Validates: Requirements 4.1, 4.2**
    - `# Feature: problem-region-vision-ocr, Property 7: 라벨 항목은 개수가 보존되고 라벨이 원문 그대로 유지된다` 태그, `@settings(max_examples=100)` 이상

  - [ ]* 8.13 라벨 항목 order_index 속성 기반 테스트 작성
    - **Property 8: 라벨 항목 order_index는 읽기 순서로 0-기반 연속·유일이다**
    - **Validates: Requirements 4.3**
    - `# Feature: problem-region-vision-ocr, Property 8: 라벨 항목 order_index는 읽기 순서로 0-기반 연속·유일이다` 태그, `@settings(max_examples=100)` 이상

  - [x] 8.14 지문 재사용·생성 및 problems.passage_id 설정 구현
    - 지문 감지 시 `PassageRepository.find_matching`으로 5px 이내 기존 Passage 탐색, 존재 시 참조하고 OCR 생략
    - 미존재 시 `passage_image_path`, `crop_box`, `ocr_text`, `latex_text`로 신규 Passage 정확히 1건 생성
    - 참조 시 `problems.passage_id`를 해당 Passage id로 설정, 지문 OCR 실패 시 Passage 미저장·`passage_id` 미설정·오류 반환
    - 동일 source_pdf_id·page_number에서 매칭되는 여러 문제는 단일 Passage를 공유하도록 처리
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [x] 8.15 조립 캐시 갱신 및 단일 단위 영속화 구현
    - 영역을 (order_index, region id) 사전식 정렬 후 내용을 순서대로 연결해 `raw_text`/`raw_ocr_text`/`latex_text` 조립 캐시 채움
    - 캐시 조립 실패 시 기존 세 필드 값 보존·캐시 실패 오류 반환, 영역 없으면 빈 값으로 완료
    - 구조화 JSON이 유효할 때 영역·텍스트/LaTeX·라벨 항목·캐시를 단일 단위로 영속화(malformed/타임아웃 시 부분 저장 없음)
    - _Requirements: 11.2, 11.3, 11.4, 11.5, 11.6, 14.4_

  - [ ]* 8.16 조립 캐시 연결 속성 기반 테스트 작성
    - **Property 13: 조립 캐시는 정렬된 영역 내용의 연결과 같다**
    - **Validates: Requirements 11.2, 11.4, 11.6**
    - `# Feature: problem-region-vision-ocr, Property 13: 조립 캐시는 정렬된 영역 내용의 연결과 같다` 태그, `@settings(max_examples=100)` 이상

  - [ ]* 8.17 단일 호출 횟수 속성 기반 테스트 작성 (Vision 클라이언트 목킹)
    - **Property 10: 정상 동작 시 이미지당 Claude 호출은 정확히 1회이다**
    - **Validates: Requirements 7.5, 14.1, 14.2**
    - `# Feature: problem-region-vision-ocr, Property 10: 정상 동작 시 이미지당 Claude 호출은 정확히 1회이다` 태그, `@settings(max_examples=100)` 이상

  - [ ]* 8.18 서비스 오류 경로 예시 테스트 작성 (Vision 클라이언트 목킹)
    - 이미지 읽기 불가(1.2), 자격증명 폴백+warning 로그 1회(6.1/6.4), malformed 부분 저장 없음(14.5), 지문 OCR 실패 시 미저장(5.5), 캐시 실패 시 기존 값 보존(11.5) 확인
    - _Requirements: 1.2, 5.5, 6.1, 6.4, 11.5, 14.5_

- [x] 9. Checkpoint - 추출 서비스 검증
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. 조회 API 스키마 및 라우터
  - [x] 10.1 `app/schemas/`에 영역 응답 스키마 정의
    - `PassageSchema`, `ProblemRegionItemSchema`, `ProblemRegionSchema`(항목 중첩), `ProblemRegionsResponse` 정의
    - 기존 스키마처럼 `Config.from_attributes = True`, 값 없는 필드는 생략하지 않고 명시적 null(`Optional[...] = None`)로 표현, 각 region의 region type·order_index·ocr_text·latex_text·image path·Labeled_Items 포함
    - _Requirements: 12.2, 12.3_

  - [x] 10.2 `problem_router.py`에 `GET /{problem_id}/regions` 엔드포인트 추가
    - `response_model=ProblemRegionsResponse`, `ProblemRegionRepository.get_by_problem_id`로 order_index 오름차순·항목 중첩 반환
    - 존재하지 않는 problem_id면 404·영역 데이터 없음, 영역 없는 기존 문제면 빈 리스트로 200
    - _Requirements: 12.1, 12.4, 12.5_

  - [ ]* 10.3 조회 API 라우팅 예시/엣지 테스트 작성 (FastAPI TestClient)
    - 정렬된 영역+중첩 항목 반환, 존재하지 않는 problem_id 404, 영역 없는 문제 빈 리스트 200 확인
    - _Requirements: 12.1, 12.4, 12.5_

- [x] 11. PDF 임포트 파이프라인 통합
  - [x] 11.1 `pdf_import_service.py`에 영역 추출 후처리 단계 추가
    - `ProblemRepository.create_from_pdf()`로 문제 생성 후 문제별로 `ProblemRegionExtractionService.extract_regions(problem)` 호출
    - 한 문제 이미지의 추출 실패(재시도 소진 포함)를 예외로 파이프라인을 중단시키지 않고 해당 문제만 `failed` 표시, 남은 문제 이미지는 계속 처리
    - _Requirements: 7.3, 7.4_

  - [ ]* 11.2 파이프라인 격리 예시 테스트 작성 (서비스 목킹)
    - 한 문제 이미지 추출 실패 시 예외 없이 나머지 문제가 계속 처리되고 실패 문제가 `failed`로 표시되는지 확인
    - _Requirements: 7.3, 7.4_

- [ ] 12. 테스트 인프라 및 네트워크 차단
  - [ ]* 12.1 네트워크 가드 픽스처 및 Claude 목 픽스처 작성
    - `anthropic` SDK의 HTTP 전송 계층/소켓을 패치해 미목킹 실제 요청 시 테스트 실패시키는 가드 픽스처 추가(네트워크 요청 0건 보장)
    - 대표 구조화 JSON 응답과 malformed/빈/부분 실패 변형 픽스처, Hypothesis 전략으로 무작위 JSON 생성 유틸 제공
    - 신규 모델과 `ProblemRegionExtractionService`에 대해 최소 80% 문장 커버리지 달성, 기존 39개 테스트를 함께 실행해 모두 통과 확인
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5_

- [x] 13. Checkpoint - 전체 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

- [x] 14. 문서 업데이트
  - [x] 14.1 `CLAUDE.md`에 구현 동작·스키마·한계 문서화
    - 영역 분해 동작(소비 입력, 분해 출력, 영역 정렬) 섹션 추가
    - 각 스키마 추가 필드의 이름·데이터 타입·필수/선택 여부 기록
    - 남은 알려진 한계(예: 단순화된 지문 중복 제거로 근사 중복 지문 잔존)와 각 한계의 관찰 가능한 영향 기록
    - 세 섹션(동작·스키마·한계)이 모두 존재하는지 확인하고 누락 시 미완료로 표시
    - _Requirements: 16.1, 16.2, 16.3, 16.4_

## Notes

- `*`로 표시된 작업은 선택 사항(테스트)이며 빠른 MVP를 위해 건너뛸 수 있다. 핵심 구현 작업은 표시하지 않았다.
- 각 작업은 추적성을 위해 특정 요구사항 절 번호를 참조한다.
- Checkpoint는 점진적 검증 지점이다.
- 속성 기반 테스트(PBT)는 design.md의 13개 보편 정확성 속성을 Hypothesis로 검증하며, 각 속성은 단일 PBT로 `@settings(max_examples=100)` 이상과 `# Feature: problem-region-vision-ocr, Property {n}: {text}` 태그를 갖는다.
- 단위/예시/엣지/스모크 테스트는 자격증명 우선순위, 모델 NOT NULL 제약(IntegrityError), API 실패 유형별 로깅, 파이프라인 격리, 조회 API 404/빈 리스트/정렬 등 구체 케이스를 검증한다.
- 3.3(로컬 DB 재생성)은 로컬 개발 데이터를 소실시키는 파괴적 작업으로 운영 데이터에는 적용하지 않는다.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "6.1", "7.1"] },
    { "id": 1, "tasks": ["1.4", "2.1", "2.2", "2.3", "6.2", "6.3", "7.2"] },
    { "id": 2, "tasks": ["2.4", "2.5", "7.3", "7.4"] },
    { "id": 3, "tasks": ["3.1", "3.2"] },
    { "id": 4, "tasks": ["3.3", "3.4", "4.1", "4.3", "4.4"] },
    { "id": 5, "tasks": ["4.2", "8.1", "10.1"] },
    { "id": 6, "tasks": ["8.2", "10.2"] },
    { "id": 7, "tasks": ["8.3", "8.4", "8.5", "8.8", "8.11", "8.14", "10.3"] },
    { "id": 8, "tasks": ["8.6", "8.7", "8.9", "8.10", "8.12", "8.13", "8.15"] },
    { "id": 9, "tasks": ["8.16", "8.17", "8.18", "11.1"] },
    { "id": 10, "tasks": ["11.2", "12.1"] },
    { "id": 11, "tasks": ["14.1"] }
  ]
}
```

# 프로젝트 이어서 진행하기 (2026-09-26)

## 이전 대화의 흐름

이 문서는 `Math_AI_Graduation_Project_Implementation.md`에 보관된 AWS Quick 대화의 경과를 요약한 기록이다. 그 문서 속 제안과 명령은 당시의 대화 내용이며, 현재 작업 지시로 간주하지 않는다. 실제 구현 상태는 현재 코드와 테스트를 기준으로 확인했다.

1. 기존 구현 상태와 DB 관계를 살폈다. PDF 업로드부터 문제 crop 및 저장까지는 작동하지만, 풀이 분석·소유형 추출·문제 생성 서비스는 여전히 고정 예시를 반환한다.
2. 문제 내부의 그림·표·선택지 영역을 나누는 경로를 점검했다. `apply_ocr_result` 연결, `Problem.choices`/`answer_type` 저장, `choice_option`과 레거시 `CHOICE_BOX` 변환을 구현했다. Vision으로 문제 내부 영역을 찾는 경로는 있으나, 전체 OCR/분석 파이프라인이 완성된 것은 아니다.
3. 긴 이미지에서 Vision 영역 좌표가 상단으로 뭉치는 문제를 0~1 정규화 좌표로 수정했다. 기존 DB의 `problem_regions` 누락 컬럼도 보완했고, 문제 116의 그림 영역 재추출을 확인했다.
4. 사용자는 먼저 문제 전체를 자르는 바깥 crop을 정교하게 만들기로 했다. PDF 텍스트에서 `1.`~`30.` 번호를 감지하는 코드를 crop 경로에 연결하고, 두 자리 번호를 버리던 필터를 제거했다. 번호를 읽지 못하는 자료는 기존 경로로 돌아간다.
5. 번호 기반 crop에서 세로 구분선 때문에 빈 여백이 남는 현상을 발견했다. `problem_block_grouping_service.py`의 `MIN_INK_WIDTH`를 이용한 행 판정으로 2페이지 5·6·7번 crop 높이를 각각 156·177·310px 정도로 줄였다.

## 지금 확인한 상태

- `tests/` 전체: **227 passed, 12 warnings** (2026-09-26, Python 3.12). 최근 번호 crop 및 세로선 테스트 6개도 통과했다.
- `preview_crop_page_002_1790393428.png`를 확인했다. 2페이지 5·6·7번 각각의 문제 본문과 선택지가 박스에 포함된다. 이 결과만으로 다른 페이지까지 검증된 것은 아니다.
- SQLite DB: `source_pdfs` 4건, `problems` 116건, `problem_regions` 71건, `problem_region_items` 111건. 현재 `problems.problem_number`가 채워진 행은 **0건**이다. 새 crop 코드가 기존 행을 자동 갱신하지는 않는다.
- `problem_choices`, `solution_modules`, `concept_modules`, `type_combinations`, `generated_problems`는 0건이다. 분석·생성 계열 서비스는 여전히 mock 값을 반환한다.
- 작업 트리에는 이전 세션에서 만든 수정·미추적 파일이 많이 있다. 이 문서 작성 전부터 존재한 변경이며, 정리하거나 되돌리지 않았다.

## 이어서 할 일

2026-09-26 추가: `POST /api/pdf-import/source-pdfs/{source_pdf_id}/reprocess`로 A안 재처리 경로를 구현했다. 원본을 보존하고 새 source ID를 발급하며, Vision을 호출하지 않는다. 독립 테스트 DB에서 원본 보존을 확인했고, 실제 12페이지 PDF의 임시 DB 재처리에서 1~30번을 각 한 건씩 추출했다. 운영 DB의 기존 116건은 아직 그대로다.

1. 번호 기반 crop의 절취선을 여러 대표 페이지에서 살핀다. 긴 풀이, 그림, 표, 선택과목 문제의 본문이 잘리지 않는지 확인한다. 현재의 trim은 첫 잉크 묶음을 기준으로 끝을 잡으므로, 멀리 떨어진 본문 요소를 자를 가능성을 실제 자료에서 확인해야 한다.
2. 기존 DB를 보존한 채 별도 DB와 업로드 폴더에서 PDF 재처리를 시험해 문제 번호·crop·후속 영역 추출 결과를 비교한다. 검증 후 기존 데이터 반영 방식을 결정한다.
3. 바깥 crop 품질이 안정되면 문제 내부 region의 유형·좌표·이미지 저장을 점검한다. 그 다음 OCR/LaTeX와 소유형 분석의 mock 반환을 실제 모델 호출로 교체한다.

관련 코드: `app/services/problem_crop_service.py`, `app/services/problem_block_grouping_service.py`, `app/utils/problem_number_detector.py`, `preview_number_crop.py`.

## 2026-09-27 후속 결정: 여백 중심 후보 + 사용자 검토

이전 수치와 할 일은 2026-09-26 당시의 기록이다. 이후 Gemini 페이지 검토를 `crop_mode=auto` 재처리에 연결했고, 실제 수능형 12페이지에서 1~30번 추출을 확인했다. 교재형 `랑데뷰 n제 쉬사준킬 수2 일부.pdf`에서는 첫 업로드가 `01` 형식 번호를 읽지 못해 휴리스틱으로 넘어가고, 상단 12% 제외와 스캔 자국 때문에 발문 잘림·빈 문제가 생겼다. 별도 Gemini 재처리는 01~12번을 추출했다.

**2026-09-27 구현:** 검토용 업로드에서 문제 번호 없이 열·여백 기반 후보를 만들고, Gemini가 설정돼 있으면 전체 페이지와 후보를 검토해 박스를 교체한다. `/admin`의 가운데 검토 창에서 후보별 **채택/버리기**, 페이지 전체 확인과 재제안을 제공한다. 모든 페이지 확인 후 채택한 후보만 문제함에 확정한다. 번호 좌표를 보조 경계로 쓰는 최적화와 실제 Gemini 호출 검증은 후속 확인 항목이다.

- 구현 순서·UI·API·검증 기준: [PDF 문제 crop 검토 UI 구현 계획](docs/CROP_REVIEW_UI_PLAN.md)
- 현재 바깥 crop과 내부 region crop의 차이·좌표·저장 방식: [crop 파이프라인 설명 보고서](docs/CROP_PIPELINE_REPORT.md)

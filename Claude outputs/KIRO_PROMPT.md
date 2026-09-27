# Kiro 전달용 프롬프트

> 아래 블록 전체를 복사해서 Kiro에게 붙여넣으세요.
> (Kiro는 프로젝트 워크스페이스에서 파일을 직접 읽을 수 있으므로, 설계 문서 2개를 먼저 읽게 합니다.)

---

math-ai-graduation-project에 "좌표 승격 + 겹침 검증 루프 복원" 기능을 구현해줘.

## 먼저 읽을 설계 문서 (반드시 먼저 읽고 그대로 따를 것)
- `Claude outputs/DESIGN_region_coord_validation.md` — 좌표 승격 + ProblemChoice 신설 + 전체 방향
- `Claude outputs/DESIGN_overlap_algorithm.md` — 겹침 검증 알고리즘 + 9b. question_body N-분할 규칙

이 두 문서가 정본(source of truth)이다. 아래는 요약이니, 상세는 문서를 따른다.

## 지켜야 할 프로젝트 관례 (중요)
- 이 프로젝트는 **DB-level ForeignKey()를 쓰지 않는다.** 새 모델도 관계는 plain integer 컬럼으로 표현.
- `region_type` 등은 **DB enum 금지**, 문자열로 저장.
- 기존 `Problem.choices` JSON 필드는 **삭제하지 않는다.**
- `create_all()`은 기존 테이블에 컬럼을 추가하지 못하므로, 새 컬럼/테이블은 README에 마이그레이션 노트를 남긴다.
- **기존 기능(PDF import pipeline, Review UI, Worksheet Builder, OCR)을 깨지 말 것.**
- 기존 전체 테스트가 계속 통과해야 한다.

## 구현 순서 (각 단계 끝에서 `python -m pytest tests/ -q` 전체 통과 확인)

1. **box_geometry 유틸** — `app/utils/box_geometry.py`
   - corner `(x1,y1,x2,y2)` 규약. `xywh_to_corner` / `corner_to_xywh` / `area` / `intersection` / `iou` / `overlap_ratio` / `contains` / `x_overlap` / `y_overlap` / `clamp_to_page` / `is_valid_corner`.
   - 순수 함수. 단위테스트 `tests/test_box_geometry.py` (가능하면 hypothesis PBT: iou∈[0,1] 등 불변식).

2. **ProblemRegion 좌표 승격** — `app/models/problem_region.py`
   - 기존 `bounding_box`(JSON) **유지**하고, 컬럼 추가: `x1,y1,x2,y2,page_width,page_height` (Float, nullable), `parent_region_id` (Integer, nullable, plain int).
   - `region_type` 값 집합을 11종으로 확장: full_problem, question_body, condition_box, figure, graph, table, choice_group, choice_option, formula, passage, unknown (문자열 저장).
   - write 시 bounding_box와 x1..y2 **동시 기록**, read 시 컬럼 우선.
   - README에 마이그레이션 노트 + `scripts/migrate_add_region_coords.py`(ALTER TABLE) 추가.
   - 테스트: `tests/test_problem_region_coords.py` (동시 기록/read 우선순위).

3. **region_overlap_validator** — `app/services/region_overlap_validator.py` (파이프라인 미연결 상태로 먼저)
   - 관계 분류(CONTAINED/HEAVY/TOUCHING/DISJOINT) + 전략(shrink / reject / merge_if_contained / clamp_to_parent).
   - `mode="candidates"`(reject 위주) / `mode="regions"`(shrink·clamp 위주).
   - choice_option 세로 겹침 분할 + index/label(①~⑤) 재부여.
   - **9b. question_body N-분할**: full_problem 내부에서 비텍스트 영역(figure/graph/table/choice_group)을 분리자로 삼아 세로 밴드 분할 → 텍스트 밴드마다 question_body region 생성(N 고정 안 함). Problem row는 절대 쪼개지 않는다.
   - `OverlapReport` 반환. fail-open(예외 시 원본 반환 + warning 1회).
   - 테스트: `tests/test_region_overlap_validator.py` (문서 §9 표 1~10 + §9b 표 11~15).

4. **_merge_boxes IoU 가드** — `app/services/problem_candidate_merge_service.py`
   - union **전에** iou/overlap_ratio 확인: HEAVY면 병합 보류(분리 유지), CONTAINED면 흡수. merge 회귀 스냅샷 테스트.

5. **파이프라인 훅 (플래그 off 기본)**
   - `ENABLE_REGION_OVERLAP_VALIDATION` 설정(기본 False)로 gating.
   - crop 후보 저장 전 `validate_and_resolve(mode="candidates")`, region 추출 후 `mode="regions")` 훅 삽입.
   - 플래그 off일 때 기존 crop 결과 **회귀 0** 확인.

6. **ProblemChoice 신설** — `app/models/problem_choice.py` + schema + repository + router
   - 필드: id, problem_id(index), region_id(nullable), choice_index(required), choice_label(nullable ①~⑤), text, latex_text, normalized_text, is_correct(bool nullable), is_distractor(bool nullable), created_at, updated_at.
   - `ProblemChoiceRepository.replace_choices_for_problem(problem_id, choices: list[str])`: 기존 삭제 → index 1부터, label ①~⑤, is_correct=null(정답 추측 금지).
   - API: GET/POST `/api/problems/{id}/choices`, PATCH/DELETE `/api/problem-choices/{id}`, POST `/api/problems/{id}/choices/replace`.
   - 테이블 생성 연결(create_tables). 테스트: repository/router.

7. **OCR apply 연동** — `app/services/problem_ocr_service.py`
   - 기존 저장 동작 전부 유지 + `Problem.choices` 저장 유지.
   - `answer_type=="multiple_choice"` & choices 있으면 `replace_choices_for_problem` 호출.
   - full_problem region 자동 생성(없을 때만): crop_box → x1..y2 변환해 좌표 채움.
   - `correct_answer`가 null이면 is_correct 전부 null 유지.

8. **Review UI** — `problem_review_detail.html` + `review_router.py`
   - "문제 영역 정보" + "객관식 보기 구조" 섹션(우선 읽기 전용). 기존 form field name 유지.
   - 조회: ProblemChoice 있으면 우선, 없으면 Problem.choices fallback. 테이블 없어도 화면 안 깨짐.

9. **좌우 감쌈(9b.3) x-2차 분할** — 후순위. 세로 밴드로 대부분 해결되면 나중에.

## 완료 조건
- `python -m pytest tests/ -q` 전체 통과 (기존 + 신규).
- 기존 PDF import / Review UI / Worksheet Builder / OCR 정상.
- OCR apply 시 choices가 Problem.choices와 ProblemChoice에 모두 저장.
- full_problem region 자동 생성.
- 원문 사이에 도형이 끼면 question_body가 N개로 분할되고 order_index로 병합 조회됨.
- 정답은 절대 추측하지 않음.
- 검증 플래그 off 시 기존 crop 결과 회귀 0.

먼저 두 설계 문서를 읽고, 1단계부터 순서대로 진행해줘. 각 단계마다 테스트를 돌려서 통과를 확인하고 다음으로 넘어가.

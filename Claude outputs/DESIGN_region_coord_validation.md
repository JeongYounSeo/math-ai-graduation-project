# 설계안: 좌표 승격 + 겹침 검증 루프 복원

> 목표: `ProblemRegion`/`ProblemChoice`의 좌표를 1급 시민(명시 컬럼)으로 승격하고,
> crop 파이프라인에 "영역 좌표 겹침 검수" 루프를 복원하여 잘못된 crop을 줄인다.
> 기존 기능(PDF import, Review UI, Worksheet, OCR)은 깨지 않는다.

---

## 0. 배경 — 현재 crop이 틀리는 근본 원인

실제 코드 분석 결과, crop 품질 저하의 근본 원인은 **좌표 검증 루프의 부재**다.

| 구성 요소 | 좌표 표현 | 좌표 검증 | 문제점 |
|---|---|---|---|
| `problem_crop_service` / `problem_block_grouping_service` | `{x, y, width, height}` (픽셀) | **세로(y) gap만** 검사 | 가로(x)는 column 전체 폭 고정 → 안내박스·옆 문제 혼입 |
| `problem_candidate_merge_service._merge_boxes` | 동일 | **없음** (union만) | 겹치는 후보를 검수 없이 병합 |
| `ProblemRegion.bounding_box` | `{left, top, right, bottom}` (JSON) | 없음 | SQL 필터/좌표 연산 불가, crop과 좌표계 단절 |

결론: 두 좌표계(crop 픽셀 vs region JSON)가 **단절**되어 있어,
"region 좌표의 min/max로 영역 간 겹침을 검수 → crop 보정" 하는 루프백이 존재하지 않는다.
과거에 하셨던 그 검수 로직이 현재 파이프라인에서 빠져 있는 상태.

---

## 1. 좌표 표준 정의 (Single Source of Truth)

### 1.1 표준 좌표 규약
- **표준 형식**: corner 방식 `(x1, y1, x2, y2)` — 좌상단/우하단. min/max 검증에 최적.
- **원점**: 이미지 좌상단, 픽셀 단위(정수). 정규화 좌표(0~1)는 `page_width/page_height`로 파생 계산.
- **불변식(invariant)**: `x1 <= x2`, `y1 <= y2`, `0 <= x1`, `x2 <= page_width`, 동일하게 y.

### 1.2 변환 유틸 (신규: `app/utils/box_geometry.py`)
crop 파이프라인의 `{x,y,width,height}` ↔ 표준 `(x1,y1,x2,y2)` 상호 변환 + 검증을 한 곳에 모은다.

```python
def xywh_to_corner(box: dict) -> tuple[float, float, float, float]: ...
def corner_to_xywh(x1, y1, x2, y2) -> dict: ...
def iou(a, b) -> float: ...                 # 두 corner box의 IoU
def contains(outer, inner, tol=0) -> bool:  # outer가 inner를 포함하는가
def clamp_to_page(box, w, h) -> tuple: ...  # 페이지 경계 clamp
def is_valid_corner(box) -> bool:           # 불변식 검사
```

---

## 2. ProblemRegion 좌표 승격 (모델 변경)

기존 `bounding_box = Column(JSON)` 을 **유지하되**(하위 호환), 명시 좌표 컬럼을 **추가**한다.
스펙 문서 요구사항과 정합.

```python
# app/models/problem_region.py 에 컬럼 추가
x1 = Column(Float, nullable=True)
y1 = Column(Float, nullable=True)
x2 = Column(Float, nullable=True)
y2 = Column(Float, nullable=True)
page_width = Column(Float, nullable=True)
page_height = Column(Float, nullable=True)
parent_region_id = Column(Integer, nullable=True)   # FK 미사용 관례 → plain int
```

- `region_type` 값 집합은 스펙의 11종(`full_problem, question_body, condition_box, figure,
  graph, table, choice_group, choice_option, formula, passage, unknown`)으로 확장.
  단 **DB enum 미사용**, 문자열 저장(기존 관례 유지).
- `bounding_box`(JSON)와 `x1..y2`(컬럼)는 **write 시 동시 기록**, read 시 컬럼 우선.
  → 마이그레이션 부담 없이 점진 전환.

### 2.1 마이그레이션 노트 (README 반영)
- `create_all()`은 **기존 테이블에 컬럼을 추가하지 않는다.**
- 개발 환경: `math_problem_engine.db` 삭제 후 재생성 권장.
- 운영/보존 데이터: 별도 `ALTER TABLE problem_regions ADD COLUMN x1 FLOAT ...` 스크립트 제공
  (`scripts/migrate_add_region_coords.py` 신규).

---

## 3. ProblemChoice 신규 추가 (좌표는 region이, 의미는 choice가)

`ProblemRegionItem`(region 종속, 좌표 위주)과 **역할 분리**한다.
- `ProblemRegion(choice_option)` = 선택지의 **좌표/이미지** (crop 대상)
- `ProblemChoice` = 선택지의 **의미**(정답 여부, distractor, 정규화 텍스트)
- 연결: `ProblemChoice.region_id`(nullable, plain int) → 해당 `choice_option` region

```python
# app/models/problem_choice.py (신규)
class ProblemChoice(Base):
    __tablename__ = "problem_choices"
    id, problem_id(index), region_id(nullable)
    choice_index(required), choice_label(nullable)  # ①②③④⑤
    text, latex_text, normalized_text
    is_correct(bool, nullable), is_distractor(bool, nullable)
    created_at, updated_at
```

**정답 추측 금지**: 답지/해설이 없으면 `is_correct=null` 유지. (스펙 명시 요구)

---

## 4. ★ 핵심: 겹침 검증 루프 복원

### 4.1 신규 검증기 `app/services/region_overlap_validator.py`
문제 하나에 속한 region들(또는 crop 후보들)의 좌표를 받아 **겹침/포함/이탈**을 검수·보정.

```python
@dataclass
class OverlapReport:
    ok: bool
    overlaps: list[tuple[int,int,float]]   # (region_i, region_j, iou)
    out_of_bounds: list[int]
    contained_pairs: list[tuple[int,int]]  # (outer, inner)

def validate_regions(regions, page_w, page_h,
                     iou_threshold=0.15) -> OverlapReport: ...

def resolve_overlaps(regions, strategy="shrink") -> list:
    # strategy:
    #  - "shrink": 겹치는 경계를 중간선에서 분할
    #  - "reject": 임계 초과 겹침 후보 탈락
    #  - "merge_if_contained": 포함 관계면 outer로 흡수
    ...
```

규칙:
- 같은 문제 내 **형제 region끼리 IoU > threshold** → 경계 조정(shrink) 또는 경고.
- 자식이 부모(`full_problem`) **경계를 벗어나면** clamp.
- `choice_option`들끼리는 서로 겹치면 안 됨(세로 정렬 기대) → y 겹침 시 분할.

### 4.2 crop 파이프라인에 삽입 지점
`problem_block_grouping_service.process_column` 이후,
`problem_candidate_merge_service.merge_classified_candidates` **직후**에 검증 훅 추가:

```
crop 후보 생성 → 분류 → merge → [신규] validate_and_resolve_overlaps → 저장
```

- merge 단계의 `_merge_boxes`는 **union 전에** IoU를 확인하고,
  겹침이 과도하면 병합 대신 분리 유지(현재는 무조건 union → 과병합 위험).
- 가로(x) 고정 폭 문제: `build_group_crop_box`가 column 전체 폭을 쓰는 대신,
  **block union x + padding**을 우선 사용하고 검증기로 옆 컬럼 침범을 clamp.

### 4.3 회귀 안전장치
- 검증기는 **기본 off 플래그**(`ENABLE_REGION_OVERLAP_VALIDATION`)로 도입 → 기존 crop 결과 회귀 방지.
- 플래그 on 시에도 "보정 실패하면 원본 유지"(fail-open)로 기존 파이프라인 불변.

---

## 5. OCR/Region 자동 생성 연동 (스펙 6단계)

`apply_ocr_result(problem_id, result)` 확장:
1. 기존 필드 저장(불변) + `Problem.choices` 저장(불변).
2. `answer_type == "multiple_choice"` & `choices` 존재 → `ProblemChoiceRepository.replace_choices_for_problem`.
3. `full_problem` region 자동 생성(없을 때만) — `crop_box` → `x1..y2` 로 좌표 채움.
   - crop_box(`{x,y,width,height}`)를 `box_geometry.xywh_to_corner`로 변환해 저장.
4. `correct_answer`가 null이면 `is_correct` 전부 null 유지.

---

## 6. API / Repository / Review UI

스펙 4·7·8단계 그대로. 요점만:
- `ProblemRegionRepository`에 `list_by_problem_and_type`, `update`, `delete`,
  `create_full_problem_region_from_problem` 추가(현재는 create/get_by_problem/delete만 존재).
- `ProblemChoiceRepository` 신규 + `replace_choices_for_problem`(index 1~, label ①~⑤, is_correct=null).
- Review UI: "문제 영역 정보" + "객관식 보기 구조" 섹션(읽기 전용부터). 기존 form field 유지.
- 조회 정책: `ProblemChoice` 있으면 우선, 없으면 `Problem.choices` fallback.

---

## 7. 테스트 계획

기존 전체 통과 유지 + 신규:
- `test_box_geometry.py` — 변환/IoU/contains/clamp 순수 함수 단위 검증(PBT 권장).
- `test_region_overlap_validator.py` — 겹침 검출·shrink·reject·contained 흡수.
- `test_problem_region_coords.py` — bounding_box(JSON)와 x1..y2 동시 기록/read 우선순위.
- `test_problem_choice_repository.py` — replace/index/label/is_correct=null.
- 크롭 회귀: 검증 플래그 on/off 각각에서 기존 crop 스냅샷과 비교(회귀 없음 보장).

---

## 8. 단계별 실행 순서 (권장)

1. `box_geometry` 유틸 + 단위테스트 (독립, 무위험).
2. `ProblemRegion` 좌표 컬럼 추가 + 동시 기록 + 마이그레이션 노트.
3. `region_overlap_validator` + 테스트 (파이프라인 미연결 상태로 먼저).
4. crop 파이프라인에 **플래그 off로** 검증 훅 삽입 → 스냅샷 회귀 확인.
5. `ProblemChoice` 모델/스키마/리포지토리/라우터 + 테스트.
6. OCR apply 연동(choices + full_problem region 자동 생성).
7. Review UI 섹션 추가.
8. 플래그 on 후 실제 crop 개선 효과 측정.

각 단계 끝에서 `python -m pytest tests/ -q` 전체 통과 확인.

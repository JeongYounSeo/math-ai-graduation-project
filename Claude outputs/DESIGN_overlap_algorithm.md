# 겹침 검증 알고리즘 상세 설계 (region_overlap_validator)

> 목적: 문제 하나에 속한 region/crop 후보들의 좌표를 받아, 겹침·포함·경계이탈을 검출하고 규칙에 따라 보정한다. 과거의 "좌표 min/max 겹침 검수" 로직을 복원한다. 순수 함수 위주 · fail-open · 플래그 gating.

---

## 0. 근본 원인 재확인 (코드 근거)

`problem_block_grouping_service.trim_whitespace_from_crop` docstring:

> "가로(x)는 column 전체 폭을 그대로 유지한다 (수식/그래프가 오른쪽으로 길게 이어질 수 있으므로 너무 타이트하게 자르지 않는다)."

→ **세로만 타이트, 가로는 column 전체 폭 고정**. 그래서

- 옆 문제/안내박스가 x축으로 혼입돼도 검출·보정 로직이 없음.
- `_merge_boxes`는 IoU 무시하고 union → 인접 후보 과병합.

검증기의 일차 임무: **가로 침범(x-overlap between columns/siblings)과 과병합**을 잡는다.

---

## 1. 좌표 계약 (box_geometry 전제)

모든 입력은 corner dict로 정규화한다.

```python
Box = {"x1": float, "y1": float, "x2": float, "y2": float}
# 불변식: x1<=x2, y1<=y2, 0<=x1, x2<=page_w, 0<=y1, y2<=page_h

```

crop 파이프라인의 `{x,y,width,height}`는 `xywh_to_corner`로 변환 후 처리, 저장 시 역변환.

### 1.1 기본 기하 함수

```python
def area(b) -> float: return max(0, b.x2-b.x1) * max(0, b.y2-b.y1)

def intersection(a, b) -> Box|None:
    ix1, iy1 = max(a.x1,b.x1), max(a.y1,b.y1)
    ix2, iy2 = min(a.x2,b.x2), min(a.y2,b.y2)
    if ix2 <= ix1 or iy2 <= iy1: return None
    return Box(ix1,iy1,ix2,iy2)

def iou(a, b) -> float:
    inter = intersection(a,b)
    if inter is None: return 0.0
    ai, bi = area(a), area(b)
    u = ai + bi - area(inter)
    return area(inter)/u if u>0 else 0.0

def overlap_ratio(a, b) -> float:
    # 작은 쪽 기준 겹침 비율(포함 판정에 유리). = inter / min(area(a),area(b))
    inter = intersection(a,b)
    if inter is None: return 0.0
    m = min(area(a), area(b))
    return area(inter)/m if m>0 else 0.0

def contains(outer, inner, tol=2.0) -> bool:
    return (inner.x1 >= outer.x1 - tol and inner.y1 >= outer.y1 - tol
            and inner.x2 <= outer.x2 + tol and inner.y2 <= outer.y2 + tol)

def x_overlap(a, b) -> float:  # 가로 겹침 길이
    return max(0.0, min(a.x2,b.x2) - max(a.x1,b.x1))

def y_overlap(a, b) -> float:  # 세로 겹침 길이
    return max(0.0, min(a.y2,b.y2) - max(a.y1,b.y1))

```

---

## 2. 임계값 (설정 가능, 기본값)

```python
IOU_SIBLING_MAX        = 0.15   # 형제 region 허용 IoU 상한
OVERLAP_RATIO_CONTAIN  = 0.80   # 작은 쪽의 80%+ 겹치면 '포함'으로 간주
Y_OVERLAP_CHOICE_MAX   = 0.20   # choice_option끼리 세로 겹침 허용 비율(높이 대비)
BOUNDARY_TOL           = 2.0    # 경계 clamp 허용 오차(px)
MIN_REGION_AREA        = 150    # 보정 후 이 미만이면 탈락

```

모두 `settings` 또는 함수 인자로 주입 가능 → 테스트에서 결정적 재현.

---

## 3. 관계 분류 (한 쌍의 box를 어떤 케이스로 볼지)

두 형제 region `a, b`에 대해 우선순위대로 판정:

```
1) CONTAINED : overlap_ratio >= OVERLAP_RATIO_CONTAIN 또는 contains(a,b)/contains(b,a)
2) HEAVY     : iou >= IOU_SIBLING_MAX (포함은 아니지만 크게 겹침)
3) TOUCHING  : 0 < iou < IOU_SIBLING_MAX (경미한 겹침 → 경고만)
4) DISJOINT  : iou == 0

```

---

## 4. 해소 전략 (resolve_overlaps)

`strategy` 파라미터로 선택. 문제 유형별 기본 매핑은 §6.

### 4.1 shrink (경계 분할) — 형제 HEAVY 겹침 기본값

겹치는 축을 판별해 **겹침이 큰 축의 중간선**에서 두 박스를 밀어낸다.

```python
def shrink_pair(a, b):
    xo, yo = x_overlap(a,b), y_overlap(a,b)
    if yo <= xo:
        # 세로 겹침이 더 작다 → 세로로 분리(위/아래 문제 경계)
        mid = (max(a.y1,b.y1) + min(a.y2,b.y2)) / 2
        top, bot = (a,b) if a.y1 <= b.y1 else (b,a)
        top.y2, bot.y1 = mid, mid
    else:
        # 가로 겹침이 더 작다 → 가로로 분리(좌/우 컬럼 침범)
        mid = (max(a.x1,b.x1) + min(a.x2,b.x2)) / 2
        left, right = (a,b) if a.x1 <= b.x1 else (b,a)
        left.x2, right.x1 = mid, mid

```

- **직관**: "덜 겹친 축으로 가른다" = 페이지 레이아웃상 실제 분리선일 가능성이 높은 방향.
- 분할 후 `area < MIN_REGION_AREA`가 되면 shrink 취소하고 reject로 fallback.

### 4.2 reject (탈락) — crop 후보 단계 기본값

- HEAVY 겹치는 두 후보 중 **ink_ratio·area가 작은 쪽을 탈락**.
- crop 후보는 "문제 하나 = 후보 하나"가 목표이므로, 과검출된 중복을 제거.

### 4.3 merge_if_contained (흡수) — 포함 관계 기본값

- `CONTAINED`면 inner를 outer로 흡수(또는 inner를 child로 강등: `parent_region_id` 설정).
- `full_problem` 안에 들어온 자식이면 병합하지 않고 **부모-자식 관계로 유지**.

### 4.4 clamp_to_parent (경계 이탈)

- 자식 region이 부모(`full_problem`) 경계를 `BOUNDARY_TOL` 넘게 벗어나면 부모 안으로 clamp.
- 페이지 경계도 동일하게 clamp.

---

## 5. choice_option 전용 규칙

객관식 보기 ①②③④⑤는 **세로로 정렬**되고 서로 겹치면 안 된다.

```python
def validate_choice_options(options):
    opts = sorted(options, key=lambda o: o.y1)
    for prev, cur in zip(opts, opts[1:]):
        h = min(prev.y2-prev.y1, cur.y2-cur.y1)
        if y_overlap(prev,cur) > Y_OVERLAP_CHOICE_MAX * h:
            mid = (prev.y2 + cur.y1) / 2
            prev.y2, cur.y1 = mid, mid   # 세로 경계 분할
    # 재정렬 후 choice_index 재부여(1..N), label ①..⑤

```

- 가로는 choice_group 폭 안으로 clamp.
- 정답 여부는 여기서 건드리지 않음(추측 금지 원칙 유지).

---

## 6. 메인 엔트리 & 전략 매핑

```python
def validate_and_resolve(regions, page_w, page_h, *, mode="regions") -> ResolveResult:
    # 1) 전부 corner로 정규화 + 페이지 clamp + 불변식 검사
    # 2) 부모(full_problem) 식별 → 자식 clamp_to_parent
    # 3) 형제쌍 관계 분류 → 전략 적용
    #      - CONTAINED  -> merge_if_contained
    #      - HEAVY      -> (mode=="candidates") reject  /  (mode=="regions") shrink
    #      - TOUCHING   -> report만
    # 4) choice_option 그룹 -> validate_choice_options
    # 5) 보정 후 재검증(1회) → 여전히 HEAVY면 report에 남기고 fail-open
    return ResolveResult(regions=..., report=OverlapReport(...))

```

`mode`:

- `"candidates"`: crop 후보(문제 분리 단계) → 과검출 제거 위주(reject).
- `"regions"`: 문제 내부 의미 영역 → 경계 조정 위주(shrink/clamp).

---

## 7. 파이프라인 삽입 & 안전장치

```
crop 후보 → 분류 → merge → [validate_and_resolve(mode="candidates")] → 저장
region 추출(Vision/규칙) →      [validate_and_resolve(mode="regions")] → 저장

```

- **플래그 gating**: `ENABLE_REGION_OVERLAP_VALIDATION`(기본 False).
- **fail-open**: 보정 중 예외/불변식 위반 → 원본 그대로 반환 + warning 로그 1회.
- **결정성**: 정렬 키 고정(y1, then x1, then id), 부동소수 비교에 `BOUNDARY_TOL`.
- `_merge_boxes` 개선: union **전에** `iou`/`overlap_ratio` 확인 → HEAVY면 병합 보류(분리 유지), CONTAINED면 흡수.

---

## 8. OverlapReport (관측/디버깅)

```python
@dataclass
class OverlapReport:
    ok: bool
    heavy: list[tuple[int,int,float]]        # (i, j, iou)
    contained: list[tuple[int,int]]          # (outer, inner)
    out_of_bounds: list[int]
    choice_fixed: list[int]
    actions: list[str]                       # 사람이 읽는 보정 로그

```

`DEBUG_CROP=1`이면 보정 전/후 박스를 오버레이 이미지로 저장(기존 draw_boxes_overlay 재사용).

---

## 9. 테스트 매트릭스 (test_region_overlap_validator.py)

| # | 입력 | 기대 |
| --- | --- | --- |
| 1 | 두 형제 세로로 조금 겹침(HEAVY, mode=regions) | 중간선 세로 분할, 겹침 해소 |
| 2 | 두 형제 가로로 컬럼 침범(HEAVY) | 중간선 가로 분할 |
| 3 | inner가 outer에 80%+ 포함 | merge_if_contained / parent 설정 |
| 4 | 자식이 부모 경계 밖 | clamp_to_parent |
| 5 | choice ①②③ 세로 겹침 | 분할 + index/label 재부여 |
| 6 | mode=candidates, 중복 후보 | 작은 쪽 reject |
| 7 | 분할 결과 area<MIN | shrink 취소 → reject fallback |
| 8 | 겹침 없음(DISJOINT) | 무변경, ok=True |
| 9 | 불변식 위반 입력 | fail-open, 원본 반환, warning |
| 10 | 플래그 off | 파이프라인 무변경(호출 skip) |

순수 함수(iou/contains/shrink)는 property-based test(hypothesis) 권장:

- `iou ∈ [0,1]`, `shrink 후 y_overlap≈0`, `clamp 후 페이지 경계 내` 등 불변식 검증.

---

## 9b. 원문 중간 도형 → question_body N-분할 규칙

> 배경: 수학 문제는 원문 텍스트 사이에 그림/그래프/표가 끼어드는 레이아웃이 흔하다. "원문은 맨 위" 전제나 "확정 영역 빼기"로는 이 케이스에서 겹침·누락이 생긴다. 해법: **원문을 하나의 큰 영역으로 잡지 않고, 끼어든 비텍스트 영역을 기준으로 **`question_body`** region을 N개로 분할한다.** 그림은 그 사이의 별도 `figure` region.

### 9b.1 원칙 — "Problem을 쪼개는 게 아니라 region을 쪼갠다"

- `Problem`(row)은 **항상 1개** 유지. 정답·배점·해설·Worksheet·분류의 단위 불변.
- 쪼개지는 것은 `question_body` **region**뿐. `order_index`로 읽기 순서 복원.
- 예:``` Problem 15 ├─ full_problem (부모, 전체 감쌈) ├─ question_body #1 order=0 y:100~~180 "함수 f(x)에 대하여…" ├─ figure order=1 y:180~~360 [그래프] └─ question_body #2 order=2 y:360~430 "…일 때 f(3)의 값은?"

```

### 9b.2 분할 알고리즘 (밴드 기반, 결정적)

`full_problem` 내부에서:

1. 비텍스트 영역(`figure/graph/table/choice_group`)의 y구간을 **분리자(separator)**로 모은다.
2. 세로축을 분리자 기준으로 밴드로 자른다: `[top .. sep1.y1] [sep1] [sep1.y2 .. sep2.y1] …`
3. 분리자가 아닌 밴드 중 **ink(텍스트)가 있는 밴드**를 각각 `question_body` region으로 만든다.
4. 결과가 0개면 원문 영역 자체가 없다는 뜻 → 경고, full_problem만 유지.
5. 결과가 1개면 기존과 동일(분할 안 함). 2개 이상이면 N-분할.

주의:

- **N은 고정하지 않는다**(그림 2개면 텍스트 3조각 가능). 리스트로 처리.
- 분리자끼리 y가 겹치면 union으로 하나의 분리자 밴드로 합친 뒤 자른다.
- 각 밴드는 §4 clamp_to_parent로 full_problem 경계 내에 둔다.

### 9b.3 좌우 감쌈(ㄴ자/ㄷ자) 예외 — 2차 x-분할

한 밴드 안에 그림과 텍스트가 **좌우로 공존**하면(그림 왼쪽, 텍스트 오른쪽 등):

- 밴드 내부에서 x축으로 한 번 더 나눠 `figure` | `question_body`로 분리.
- 빈도가 낮으므로 **후순위 구현**. 1차(세로 밴드)만으로 대부분 해결.

### 9b.4 조회 시 텍스트 병합 정책

- **저장은 조각**(`question_body` N개), **조회는 병합**.
- `Problem`의 대표 원문 텍스트는 `question_body` region들을 `order_index` 순으로 이어붙여 재구성(검색·분류·유사문제 생성용).
- 병합은 조회 계층(repository/service)에서 수행하고 조각 자체는 보존.

### 9b.5 이 규칙이 해소하는 것

- ✅ "원문이 맨 위" 전제 붕괴 문제 (그림이 중간에 껴도 밴드로 자연 분리)
- ✅ "빼기의 겹침" 문제 (밴드는 정의상 서로 겹치지 않음)
- ✅ 텍스트 OCR 품질 (그림 영역을 OCR 입력에서 배제)

### 9b.6 테스트 추가 (test_region_overlap_validator.py 확장)

| # | 입력 | 기대 |
| --- | --- | --- |
| 11 | 원문 사이 figure 1개 | question_body 2개 + figure 1개, order 0/1/2 |
| 12 | 원문 사이 figure 2개 | question_body 3개 (N-분할) |
| 13 | figure 없음 | question_body 1개 (분할 안 함) |
| 14 | 분리자 y겹침 2개 | union 후 1개 분리자로 처리 |
| 15 | 병합 조회 | order_index 순으로 텍스트 결합 |

---

## 10. 구현 순서

1. `box_geometry.py` (§1 함수) + 단위테스트.
2. `region_overlap_validator.py` 순수 로직(§3~6) + 테스트(§9) — 파이프라인 미연결.
3. `_merge_boxes` IoU 가드 추가(§7) + merge 회귀 스냅샷.
4. crop/region 파이프라인에 플래그 off로 훅 삽입 → 회귀 0 확인.
5. 플래그 on, sample.pdf로 보정 효과 측정(오버레이 비교).
6. 9b N-분할(세로 밴드) 구현 + 병합 조회 정책 + 테스트(11~15). 좌우 감쌈(9b.3)은 후순위.

```

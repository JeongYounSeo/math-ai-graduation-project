"""겹침 검증 훅(파이프라인 삽입) 테스트 — 플래그 off 회귀 0 + 플래그 on 동작.

정본 설계: ``Claude outputs/DESIGN_overlap_algorithm.md`` §7,
``Claude outputs/DESIGN_region_coord_validation.md`` §4.2, §4.3.

이 파일은 파이프라인에 **플래그 off 기본**으로 삽입된 두 훅을 검증한다.

- 훅 1(candidates): ``PDFImportService._apply_candidate_overlap_validation``
- 훅 2(regions):    ``PDFImportService._apply_region_overlap_validation``

핵심 안전 요구: **플래그 off일 때 기존 crop 결과 회귀 0**(검증기 미호출, 입력 그대로).

설정 플래그는 ``os.getenv`` 를 @property 안에서 매번 읽으므로 env monkeypatch 로
True/False 를 전환한다(tests/test_config_claude.py 패턴).
"""

import importlib

import pytest

import app.core.config as config_module
import app.services.pdf_import_service as pdf_import_module
from app.core.config import Settings
from app.services.region_overlap_validator import ResolveResult, OverlapReport, Region


# ---------------------------------------------------------------------------
# 설정 플래그 자체 검증 (test_config_claude.py 패턴)
# ---------------------------------------------------------------------------
def test_flag_default_is_false(monkeypatch):
    monkeypatch.delenv("ENABLE_REGION_OVERLAP_VALIDATION", raising=False)
    assert Settings().ENABLE_REGION_OVERLAP_VALIDATION is False


def test_flag_true_when_env_true(monkeypatch):
    monkeypatch.setenv("ENABLE_REGION_OVERLAP_VALIDATION", "true")
    assert Settings().ENABLE_REGION_OVERLAP_VALIDATION is True
    monkeypatch.setenv("ENABLE_REGION_OVERLAP_VALIDATION", "TRUE")
    assert Settings().ENABLE_REGION_OVERLAP_VALIDATION is True


def test_flag_false_for_other_values(monkeypatch):
    monkeypatch.setenv("ENABLE_REGION_OVERLAP_VALIDATION", "0")
    assert Settings().ENABLE_REGION_OVERLAP_VALIDATION is False
    monkeypatch.setenv("ENABLE_REGION_OVERLAP_VALIDATION", "yes")
    assert Settings().ENABLE_REGION_OVERLAP_VALIDATION is False


# ---------------------------------------------------------------------------
# 훅 헬퍼를 DB/네트워크 없이 테스트하기 위한 경량 스텁 서비스.
# PDFImportService.__init__ 은 무거운 의존성을 만들므로, 훅 헬퍼는 self 에서
# settings/logger/region_extraction_service/db 만 참조한다는 점을 이용해
# 바운드 메서드만 떼어 스텁 인스턴스에 붙여 호출한다.
# ---------------------------------------------------------------------------
class _StubService:
    """훅 헬퍼 두 개만 바인딩한 경량 스텁."""

    def __init__(self):
        self.db = None
        self.region_extraction_service = None

    # 실제 구현을 그대로 빌려온다(언바운드 함수로 호출).
    _apply_candidate_overlap_validation = (
        pdf_import_module.PDFImportService._apply_candidate_overlap_validation
    )
    _apply_region_overlap_validation = (
        pdf_import_module.PDFImportService._apply_region_overlap_validation
    )
    _resolve_page_size = staticmethod(
        pdf_import_module.PDFImportService._resolve_page_size
    )


def _sample_merged_results():
    """merged_results 형태(각 항목은 dict, crop_box 는 xywh, 부가 필드 포함)."""
    return [
        {
            "page_number": 1,
            "problem_number": 1,
            "elective_subject": "common",
            "crop_box": {"x": 10.0, "y": 10.0, "width": 100.0, "height": 100.0},
            "original_candidate_boxes": [{"x": 10.0, "y": 10.0, "width": 100.0, "height": 100.0}],
            "status": "unclassified",
            "source_image_path": "/tmp/page.png",
        },
        {
            "page_number": 1,
            "problem_number": 2,
            "elective_subject": "common",
            "crop_box": {"x": 200.0, "y": 200.0, "width": 100.0, "height": 100.0},
            "original_candidate_boxes": [{"x": 200.0, "y": 200.0, "width": 100.0, "height": 100.0}],
            "status": "unclassified",
            "source_image_path": "/tmp/page.png",
        },
    ]


# ---------------------------------------------------------------------------
# 훅 1 (candidates)
# ---------------------------------------------------------------------------
def test_candidate_hook_flag_off_returns_input_unchanged(monkeypatch):
    """플래그 off 회귀 0: 입력과 완전히 동일한 객체를 그대로 반환한다."""
    monkeypatch.delenv("ENABLE_REGION_OVERLAP_VALIDATION", raising=False)

    svc = _StubService()
    merged = _sample_merged_results()
    result = svc._apply_candidate_overlap_validation(merged, 1000.0, 1000.0)

    # 동일 객체(identity) 반환 → 어떤 복사/변형도 없음.
    assert result is merged
    assert result == _sample_merged_results()


def test_candidate_hook_flag_off_does_not_call_validator(monkeypatch):
    """플래그 off면 validator(validate_and_resolve)를 호출조차 하지 않는다."""
    monkeypatch.delenv("ENABLE_REGION_OVERLAP_VALIDATION", raising=False)

    called = {"n": 0}

    def _spy(*args, **kwargs):
        called["n"] += 1
        raise AssertionError("플래그 off에서 validator가 호출되면 안 된다")

    monkeypatch.setattr(pdf_import_module, "validate_and_resolve", _spy)

    svc = _StubService()
    merged = _sample_merged_results()
    result = svc._apply_candidate_overlap_validation(merged, 1000.0, 1000.0)

    assert called["n"] == 0
    assert result is merged


def test_candidate_hook_flag_on_rejects_overlap_and_preserves_fields(monkeypatch):
    """플래그 on: HEAVY 겹침 후보 두 개 중 하나가 reject 되어 개수가 줄고,
    남은 항목의 부가 필드(problem_number 등)가 보존된다."""
    monkeypatch.setenv("ENABLE_REGION_OVERLAP_VALIDATION", "true")

    svc = _StubService()
    # HEAVY 겹침(iou>=0.15)이지만 포함(overlap_ratio>=0.8)은 아닌 두 후보.
    # A(10000) vs B(9000): 교차 3600 → iou≈0.234(HEAVY), overlap_ratio=0.4(<0.8).
    # candidates 모드 → 작은 쪽(B) reject.
    merged = [
        {
            "problem_number": 7,
            "elective_subject": "calculus",
            "crop_box": {"x": 0.0, "y": 0.0, "width": 100.0, "height": 100.0},
            "extra": "keep-big",
        },
        {
            "problem_number": 8,
            "elective_subject": "calculus",
            "crop_box": {"x": 60.0, "y": 0.0, "width": 100.0, "height": 90.0},
            "extra": "keep-small",
        },
    ]
    result = svc._apply_candidate_overlap_validation(merged, 1000.0, 1000.0)

    # candidates 모드에서 HEAVY → 작은 쪽 reject → 1개만 남는다.
    assert len(result) == 1
    survivor = result[0]
    # 큰 쪽(problem_number=7)이 생존, 부가 필드 보존.
    assert survivor["problem_number"] == 7
    assert survivor["extra"] == "keep-big"
    assert survivor["elective_subject"] == "calculus"
    # crop_box 는 여전히 xywh dict 규약을 유지.
    assert set(survivor["crop_box"]) == {"x", "y", "width", "height"}


def test_candidate_hook_flag_on_disjoint_preserves_all(monkeypatch):
    """플래그 on 이어도 겹치지 않는 후보는 모두 보존되고 부가 필드도 유지된다."""
    monkeypatch.setenv("ENABLE_REGION_OVERLAP_VALIDATION", "true")

    svc = _StubService()
    merged = _sample_merged_results()
    result = svc._apply_candidate_overlap_validation(merged, 1000.0, 1000.0)

    assert len(result) == 2
    assert {r["problem_number"] for r in result} == {1, 2}
    for r in result:
        assert set(r["crop_box"]) == {"x", "y", "width", "height"}


def test_candidate_hook_flag_on_failopen_on_validator_exception(monkeypatch):
    """플래그 on 에서 validator 가 예외를 던져도 훅은 원본을 반환하고 전파하지 않는다."""
    monkeypatch.setenv("ENABLE_REGION_OVERLAP_VALIDATION", "true")

    def _boom(*args, **kwargs):
        raise RuntimeError("validator 폭발")

    monkeypatch.setattr(pdf_import_module, "validate_and_resolve", _boom)

    svc = _StubService()
    merged = _sample_merged_results()
    # 예외가 전파되지 않아야 한다.
    result = svc._apply_candidate_overlap_validation(merged, 1000.0, 1000.0)

    assert result is merged  # fail-open: 원본 그대로.


# ---------------------------------------------------------------------------
# 훅 2 (regions)
# ---------------------------------------------------------------------------
class _FakeRegionRepo:
    def __init__(self, regions):
        self._regions = regions
        self.get_calls = 0

    def get_by_problem_id(self, problem_id):
        self.get_calls += 1
        return list(self._regions)


class _FakeExtractionService:
    def __init__(self, repo):
        self.region_repository = repo


class _FakeProblem:
    def __init__(self, pid=1):
        self.id = pid
        self.page_image_path = None


class _FakeDB:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _make_region_service(db, repo):
    svc = _StubService()
    svc.db = db
    svc.region_extraction_service = _FakeExtractionService(repo)
    return svc


def test_region_hook_flag_off_does_nothing(monkeypatch):
    """플래그 off 회귀 0: region 조회조차 하지 않고, 좌표도 변하지 않는다."""
    monkeypatch.delenv("ENABLE_REGION_OVERLAP_VALIDATION", raising=False)

    repo = _FakeRegionRepo(regions=[])
    db = _FakeDB()
    svc = _make_region_service(db, repo)

    svc._apply_region_overlap_validation(_FakeProblem())

    # 플래그 off: 조회/커밋/롤백 모두 없음.
    assert repo.get_calls == 0
    assert db.commits == 0
    assert db.rollbacks == 0


def test_region_hook_flag_off_does_not_call_validator(monkeypatch):
    """플래그 off면 validator 를 호출하지 않는다."""
    monkeypatch.delenv("ENABLE_REGION_OVERLAP_VALIDATION", raising=False)

    def _spy(*args, **kwargs):
        raise AssertionError("플래그 off에서 validator 호출 금지")

    monkeypatch.setattr(pdf_import_module, "validate_and_resolve", _spy)

    repo = _FakeRegionRepo(regions=[])
    db = _FakeDB()
    svc = _make_region_service(db, repo)
    svc._apply_region_overlap_validation(_FakeProblem())  # 예외 없이 통과해야 함.


class _FakeDBRegion:
    """get_box/set_box 를 흉내내는 경량 ProblemRegion 스텁."""

    def __init__(self, rid, corner, region_type="question_body", page_w=1000.0, page_h=1000.0):
        self.id = rid
        self._corner = corner
        self.region_type = region_type
        self.parent_region_id = None
        self.page_width = page_w
        self.page_height = page_h
        self.set_calls = 0

    def get_box(self):
        return self._corner

    def set_box(self, corner, page_width=None, page_height=None):
        self.set_calls += 1
        if isinstance(corner, dict):
            self._corner = (corner["x1"], corner["y1"], corner["x2"], corner["y2"])
        else:
            self._corner = tuple(float(v) for v in corner)


def test_region_hook_flag_on_updates_and_commits(monkeypatch):
    """플래그 on: 세로로 겹친 형제 region 두 개를 보정(set_box)하고 commit 한다."""
    monkeypatch.setenv("ENABLE_REGION_OVERLAP_VALIDATION", "true")

    # 세로로 크게 겹치는 두 형제(HEAVY) → mode=regions → shrink.
    r1 = _FakeDBRegion(1, (0.0, 0.0, 100.0, 100.0))
    r2 = _FakeDBRegion(2, (0.0, 40.0, 100.0, 140.0))
    repo = _FakeRegionRepo(regions=[r1, r2])
    db = _FakeDB()
    svc = _make_region_service(db, repo)

    svc._apply_region_overlap_validation(_FakeProblem())

    assert repo.get_calls == 1
    assert db.commits == 1
    assert db.rollbacks == 0
    # 최소한 하나의 region 은 set_box 로 좌표가 재기록되었어야 한다.
    assert (r1.set_calls + r2.set_calls) >= 1


def test_region_hook_flag_on_failopen_on_exception(monkeypatch):
    """플래그 on 에서 validator 예외 시 rollback + 예외 미전파(fail-open)."""
    monkeypatch.setenv("ENABLE_REGION_OVERLAP_VALIDATION", "true")

    def _boom(*args, **kwargs):
        raise RuntimeError("regions validator 폭발")

    monkeypatch.setattr(pdf_import_module, "validate_and_resolve", _boom)

    r1 = _FakeDBRegion(1, (0.0, 0.0, 100.0, 100.0))
    repo = _FakeRegionRepo(regions=[r1])
    db = _FakeDB()
    svc = _make_region_service(db, repo)

    # 예외가 전파되지 않아야 한다.
    svc._apply_region_overlap_validation(_FakeProblem())
    assert db.rollbacks == 1
    assert db.commits == 0

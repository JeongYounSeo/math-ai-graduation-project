"""TASK 6.2 — 이미지 저장 경로 규칙 속성 기반 테스트(Property 12).
TASK 6.3 — 식별자 누락/덮어쓰기 예시·엣지 테스트.

storage.DEFAULT_UPLOAD_ROOT는 import 시점에 고정되므로, 테스트에서는 그 값을
tmp Path로 monkeypatch하여 리포지토리를 오염시키지 않는다.

Requirements: 10.1, 10.2 (6.2), 10.3, 10.4 (6.3)
"""

from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# NOTE: app.core.storage 는 각 테스트/함수 안에서 lazy import 한다.
# 모듈 최상단에서 import 하면 pytest collection 시점에 storage 모듈이 조기 로드되어
# DEFAULT_UPLOAD_ROOT(모듈 import 시점 고정)가 default("uploads")로 굳어지고,
# UPLOADS_ROOT 환경변수에 의존하는 다른 테스트(test_pdf_import_flow)를 깨뜨린다.


# 경로 구분자·공백을 배제한 안전한 식별자 문자 집합.
_SAFE_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"


# Windows 예약 장치명(대소문자 무관). 디렉터리 이름으로 쓸 수 없어 mkdir 이 실패한다.
# 실제 식별자(PDF_xxxx, 정수)에는 등장하지 않으므로 경로 규칙 검증에서 제외한다.
_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def _safe_text_ids():
    def _not_reserved(s: str) -> bool:
        lowered = s.lower()
        stem = lowered.split(".", 1)[0]
        return lowered not in _WINDOWS_RESERVED and stem not in _WINDOWS_RESERVED
    return st.text(alphabet=_SAFE_ALPHABET, min_size=1, max_size=20).filter(_not_reserved)


def _identifier_strategy():
    # 문자열 식별자 또는 양의 정수 식별자.
    return st.one_of(_safe_text_ids(), st.integers(min_value=1, max_value=10_000))


# ---------------------------------------------------------------------------
# TASK 6.2 — Property 12 (PBT)
# ---------------------------------------------------------------------------
# Feature: problem-region-vision-ocr, Property 12: 이미지 저장 경로는 규칙 패턴을 따른다
@settings(max_examples=100)
@given(
    source_pdf_id=_identifier_strategy(),
    problem_id=_identifier_strategy(),
    region_id=_identifier_strategy(),
    item_id=_identifier_strategy(),
)
def test_image_paths_follow_convention(
    tmp_path_factory, source_pdf_id, problem_id, region_id, item_id
):
    import app.core.storage as storage
    from app.core.storage import get_item_image_path, get_region_image_path

    # @given 본문 안에서 격리된 tmp 루트를 만들고 DEFAULT_UPLOAD_ROOT를 교체한다.
    tmp_root = tmp_path_factory.mktemp("uploads_root")
    original_root = storage.DEFAULT_UPLOAD_ROOT
    storage.DEFAULT_UPLOAD_ROOT = Path(tmp_root)
    try:
        region_path = get_region_image_path(source_pdf_id, problem_id, region_id)
        item_path = get_item_image_path(source_pdf_id, problem_id, item_id)
    finally:
        storage.DEFAULT_UPLOAD_ROOT = original_root

    # 영역 경로: .../problems/{source}/{problem}/regions/{region}.png
    assert region_path.name == f"{region_id}.png"
    assert region_path.parent.name == "regions"
    assert region_path.parent.parent.name == str(problem_id)
    assert region_path.parent.parent.parent.name == str(source_pdf_id)
    assert region_path.parent.parent.parent.parent.name == "problems"

    # 항목 경로: .../problems/{source}/{problem}/items/{item}.png
    assert item_path.name == f"{item_id}.png"
    assert item_path.parent.name == "items"
    assert item_path.parent.parent.name == str(problem_id)
    assert item_path.parent.parent.parent.name == str(source_pdf_id)
    assert item_path.parent.parent.parent.parent.name == "problems"

    # 부모 디렉터리가 실제로 생성되었는지 확인(mkdir 발생).
    assert region_path.parent.is_dir()
    assert item_path.parent.is_dir()


# ---------------------------------------------------------------------------
# TASK 6.3 — 식별자 누락/덮어쓰기 (Req 10.3, 10.4)
# ---------------------------------------------------------------------------
@pytest.fixture
def tmp_upload_root(tmp_path, monkeypatch):
    """DEFAULT_UPLOAD_ROOT를 tmp 디렉터리로 교체한다(monkeypatch가 teardown 복원)."""
    import app.core.storage as storage

    monkeypatch.setattr(storage, "DEFAULT_UPLOAD_ROOT", Path(tmp_path))
    return Path(tmp_path)


@pytest.mark.parametrize("missing", ["", "   ", None])
def test_region_path_missing_source_pdf_id_raises(tmp_upload_root, missing):
    from app.core.storage import get_region_image_path

    with pytest.raises(ValueError) as exc:
        get_region_image_path(missing, "prob1", "reg1")
    assert "source_pdf_id" in str(exc.value)


@pytest.mark.parametrize("missing", ["", "   ", None])
def test_region_path_missing_region_id_raises(tmp_upload_root, missing):
    from app.core.storage import get_region_image_path

    with pytest.raises(ValueError) as exc:
        get_region_image_path("src1", "prob1", missing)
    assert "region_id" in str(exc.value)


@pytest.mark.parametrize("missing", ["", "   ", None])
def test_item_path_missing_item_id_raises(tmp_upload_root, missing):
    from app.core.storage import get_item_image_path

    with pytest.raises(ValueError) as exc:
        get_item_image_path("src1", "prob1", missing)
    assert "item_id" in str(exc.value)


def test_missing_identifier_writes_no_file(tmp_upload_root):
    from app.core.storage import get_region_image_path

    # 오류 발생 시 어떤 파일도 기록되지 않아야 한다(Req 10.3).
    with pytest.raises(ValueError):
        get_region_image_path("", "prob1", "reg1")

    # tmp 루트에 problems 하위 파일이 만들어지지 않았는지 확인.
    created = list(tmp_upload_root.rglob("*.png"))
    assert created == []


def test_region_path_is_fixed_and_overwrites(tmp_upload_root):
    from app.core.storage import get_region_image_path

    # 같은 식별자로 두 번 호출하면 동일한 고정 경로를 반환한다(Req 10.4).
    p1 = get_region_image_path("src1", "prob1", "reg1")
    p2 = get_region_image_path("src1", "prob1", "reg1")
    assert p1 == p2

    # 파일을 쓰고 다시 호출해도 같은 경로 → 덮어쓰기 대상 유지.
    p1.write_bytes(b"first")
    p3 = get_region_image_path("src1", "prob1", "reg1")
    assert p3 == p1
    assert p3.read_bytes() == b"first"


def test_item_path_is_fixed_and_overwrites(tmp_upload_root):
    from app.core.storage import get_item_image_path

    p1 = get_item_image_path("src1", "prob1", "item1")
    p2 = get_item_image_path("src1", "prob1", "item1")
    assert p1 == p2

    p1.write_bytes(b"first")
    p1.write_bytes(b"second")  # 실제 덮어쓰기
    assert p1.read_bytes() == b"second"

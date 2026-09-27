"""번호 기반 crop 분할 테스트 (2026-09-25).

_crop_by_problem_numbers: 감지된 문제번호 y좌표(x zoom)를 경계로 컬럼별 crop.
- 좌표 변환(원본 x zoom = 렌더 이미지 좌표)
- 컬럼 분리, 마지막 문제는 페이지 바닥까지
- 번호 <2개면 None (스캔본/논술 하위호환)
"""
from app.services.problem_crop_service import _crop_by_problem_numbers, RENDER_ZOOM
from app.utils.problem_number_detector import DetectedProblemNumber


class FakePage:
    """detect_problem_numbers_from_pdf_page 를 우회하기 위한 최소 stub 는 아니고,
    실제 감지 함수가 page.get_text('words') 를 부르므로 words 를 주입한다."""
    class _Rect:
        width = 842.0
        height = 1191.0
    rect = _Rect()

    def __init__(self, words):
        self._words = words

    def get_text(self, kind):
        assert kind == "words"
        return self._words


def _word(text, x0, y0):
    # PyMuPDF words 튜플: (x0,y0,x1,y1,text,block,line,word_no)
    return (x0, y0, x0 + 15, y0 + 18, text, 0, 0, 0)


def test_number_based_crop_page1():
    # page1 실제 감지값 재현: 1.@(88,286) 2.@(88,668) 3.@(437,231) 4.@(437,645)
    words = [
        _word("1.", 88, 286), _word("2.", 88, 668),
        _word("3.", 437, 231), _word("4.", 437, 645),
    ]
    page = FakePage(words)
    W, H = 1684, 2382  # 렌더 이미지(zoom=2.0)
    cands = _crop_by_problem_numbers("p.png", 1, W, H, page)
    assert cands is not None
    by_num = {c.problem_number: c.crop_box for c in cands}
    assert set(by_num) == {1, 2, 3, 4}

    z = RENDER_ZOOM
    # 1번: y=286*z, height=(668-286)*z, 좌측 컬럼 x=0
    assert by_num[1]["x"] == 0
    assert by_num[1]["y"] == int(286 * z)
    assert by_num[1]["height"] == int(668 * z) - int(286 * z)
    # 2번: 마지막(좌측)이라 바닥까지
    assert by_num[2]["y"] == int(668 * z)
    assert by_num[2]["height"] == H - int(668 * z)
    # 3번: 우측 컬럼 x=842
    assert by_num[3]["x"] == W // 2
    assert by_num[3]["y"] == int(231 * z)
    # 4번: 우측 마지막이라 바닥까지
    assert by_num[4]["height"] == H - int(645 * z)


def test_single_number_returns_none():
    """번호 1개면 None (밀도/폴백 경로로 넘김)."""
    page = FakePage([_word("1.", 88, 286)])
    assert _crop_by_problem_numbers("p.png", 1, 1684, 2382, page) is None


def test_no_page_returns_none():
    assert _crop_by_problem_numbers("p.png", 1, 1684, 2382, None) is None

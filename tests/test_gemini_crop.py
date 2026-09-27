"""Offline checks for page-level Gemini crop review and B-path persistence."""

import importlib
import json as json_module

import httpx
from fastapi.testclient import TestClient
from PIL import Image

from app.services.gemini_page_crop_client import GeminiCropError, GeminiPageCropClient
from app.services.problem_crop_service import crop_page_with_gemini
from app.utils.problem_number_detector import DetectedProblemNumber


def test_gemini_client_sends_one_annotated_page_and_parses_output(tmp_path):
    page_path = tmp_path / "page.png"
    Image.new("RGB", (800, 1000), "white").save(page_path)
    calls = []

    def fake_post(url, *, headers, json, timeout):
        calls.append((url, headers, json, timeout))
        decision = {"verdict": "accept_a", "reason": "complete", "boxes": []}
        return httpx.Response(200, json={
            "status": "completed",
            "steps": [{"type": "model_output", "content": [{"type": "text", "text": json_module.dumps(decision)}]}],
            "usage": {"total_input_tokens": 20, "total_output_tokens": 5},
        })

    result = GeminiPageCropClient("test-key", post=fake_post).inspect(page_path, [
        {"problem_number": 1, "crop_box": {"x": 10, "y": 20, "width": 300, "height": 400}}
    ])
    assert result["verdict"] == "accept_a"
    assert result["_usage"]["total_input_tokens"] == 20
    assert len(calls) == 1
    assert calls[0][1] == {"x-goog-api-key": "test-key"}
    assert [part["type"] for part in calls[0][2]["input"]] == ["text", "image"]
    assert calls[0][2]["response_format"]["mime_type"] == "application/json"


def test_crop_page_replaces_or_marks_invalid_boxes_for_review(tmp_path):
    page_path = tmp_path / "page.png"
    Image.new("RGB", (800, 1000), "white").save(page_path)

    class Stub:
        def __init__(self, decision):
            self.decision = decision
            self.a_boxes = None

        def inspect(self, _path, a_boxes):
            self.a_boxes = a_boxes
            return self.decision

    client = Stub({
        "verdict": "replace", "reason": "A missed questions",
        "boxes": [
            {"number": 1, "box_2d": [100, 50, 400, 450]},
            {"number": 2, "box_2d": [500, 50, 900, 450]},
        ],
    })
    result = crop_page_with_gemini(page_path, 1, None, client)
    assert client.a_boxes == []
    assert result.method == "gemini" and not result.needs_review
    assert [c.problem_number for c in result.candidates] == [1, 2]
    assert result.candidates[0].crop_box == {"x": 40, "y": 100, "width": 320, "height": 300}

    client.decision = {
        "verdict": "replace", "reason": "bad", "boxes": [
            {"number": 1, "box_2d": [100, 50, 600, 450]},
            {"number": 2, "box_2d": [200, 100, 700, 500]},
        ],
    }
    rejected = crop_page_with_gemini(page_path, 1, None, client)
    assert rejected.needs_review
    assert rejected.method == "heuristic_unverified"


def test_a_boxes_are_kept_when_gemini_approves_and_flagged_on_error(tmp_path, monkeypatch):
    page_path = tmp_path / "page.png"
    Image.new("RGB", (800, 1000), "white").save(page_path)
    numbers = [
        DetectedProblemNumber(problem_number=1, page_number=1, x=50, y=100, width=10, height=10, column="left"),
        DetectedProblemNumber(problem_number=2, page_number=1, x=50, y=300, width=10, height=10, column="left"),
    ]
    monkeypatch.setattr(
        "app.utils.problem_number_detector.detect_problem_numbers_from_pdf_page",
        lambda *_args: numbers,
    )

    class Approved:
        def inspect(self, _path, a_boxes):
            assert len(a_boxes) == 2
            return {"verdict": "accept_a", "reason": "complete", "boxes": []}

    approved = crop_page_with_gemini(page_path, 1, object(), Approved())
    assert approved.method == "number_verified"
    assert not approved.needs_review
    assert [c.problem_number for c in approved.candidates] == [1, 2]

    class Failed:
        def inspect(self, _path, _a_boxes):
            raise GeminiCropError("provider unavailable")

    failed = crop_page_with_gemini(page_path, 1, object(), Failed())
    assert failed.method == "number_unverified"
    assert failed.needs_review
    assert [c.problem_number for c in failed.candidates] == [1, 2]


def test_auto_reprocess_saves_gemini_boxes_without_pdf_text(tmp_path, monkeypatch):
    import fitz

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'gemini.db'}")
    monkeypatch.setenv("UPLOADS_ROOT", str(tmp_path / "uploads"))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("STRICT_TEXT_FILTER", "true")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)

    import app.core.database as database_module
    import app.core.storage as storage_module
    import app.main as main_module
    import app.services.gemini_page_crop_client as gemini_module

    importlib.reload(database_module)
    importlib.reload(storage_module)
    importlib.reload(main_module)
    client = TestClient(main_module.app)

    source_path = tmp_path / "blank.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(source_path)
    doc.close()
    with source_path.open("rb") as file_obj:
        response = client.post("/api/pdf-import/upload", files={"file": ("blank.pdf", file_obj, "application/pdf")})
    assert response.status_code == 200, response.text
    original_id = response.json()["source_pdf_id"]

    def fake_inspect(_self, _page_image_path, a_boxes):
        assert a_boxes == []
        return {"verdict": "replace", "reason": "two problems", "boxes": [
            {"number": 1, "box_2d": [100, 50, 400, 450]},
            {"number": 2, "box_2d": [500, 50, 900, 450]},
        ], "_usage": {"total_input_tokens": 100, "total_output_tokens": 30}}

    monkeypatch.setattr(gemini_module.GeminiPageCropClient, "inspect", fake_inspect)
    response = client.post(f"/api/pdf-import/source-pdfs/{original_id}/reprocess?crop_mode=auto")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["source_pdf_id"] != original_id
    assert result["status"] == "imported"
    assert result["imported_problem_count"] == 2
    assert result["page_reports"][0]["method"] == "gemini"
    assert result["page_reports"][0]["input_tokens"] == 100

    from app.models.problem import Problem
    db = database_module.SessionLocal()
    try:
        problems = db.query(Problem).filter(Problem.source_pdf_id == result["source_pdf_id"]).all()
        assert {problem.problem_number for problem in problems} == {1, 2}
        assert db.query(Problem).filter(Problem.source_pdf_id == original_id).count() == 0
    finally:
        db.close()

    def failed_inspect(_self, _page_image_path, _a_boxes):
        raise GeminiCropError("provider unavailable")

    monkeypatch.setattr(gemini_module.GeminiPageCropClient, "inspect", failed_inspect)
    failed = client.post(f"/api/pdf-import/source-pdfs/{original_id}/reprocess?crop_mode=auto")
    assert failed.status_code == 200, failed.text
    assert failed.json()["status"] == "needs_review"
    assert failed.json()["page_reports"][0]["needs_review"] is True

    monkeypatch.delenv("GEMINI_API_KEY")
    missing_key = client.post(f"/api/pdf-import/source-pdfs/{original_id}/reprocess?crop_mode=auto")
    assert missing_key.status_code == 409
    assert "GEMINI_API_KEY" in missing_key.json()["detail"]


def test_unconfigured_client_raises():
    try:
        GeminiPageCropClient(None).inspect("unused.png", [])
    except GeminiCropError as exc:
        assert "GEMINI_API_KEY" in str(exc)
    else:
        raise AssertionError("missing key should fail before image access")

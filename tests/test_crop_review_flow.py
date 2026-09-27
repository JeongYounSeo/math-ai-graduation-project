import importlib

import fitz
from fastapi.testclient import TestClient
from PIL import Image


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'review.db'}")
    monkeypatch.setenv("UPLOADS_ROOT", str(tmp_path / "uploads"))
    monkeypatch.setenv("GEMINI_API_KEY", "")
    import app.core.database as database
    import app.core.storage as storage
    import app.main as main
    importlib.reload(database)
    importlib.reload(storage)
    importlib.reload(main)
    return TestClient(main.app)


def _pdf(tmp_path):
    path = tmp_path / "review.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((70, 100), "01 Find the value of x.", fontsize=16)
    page.insert_text((70, 155), "x + 2 = 5", fontsize=16)
    page.insert_text((70, 430), "02 Find the value of y.", fontsize=16)
    page.insert_text((70, 485), "y + 3 = 7", fontsize=16)
    document.new_page()  # Blank page should produce no proposals.
    document.save(path)
    document.close()
    return path


def test_review_upload_decisions_retry_and_finalize(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    path = _pdf(tmp_path)
    with path.open("rb") as stream:
        response = client.post("/api/pdf-import/review-uploads",
                               files={"file": ("review.pdf", stream, "application/pdf")})
    assert response.status_code == 200, response.text
    source_id = response.json()["source_pdf_id"]
    assert response.json()["total_pages"] == 2
    assert client.get(f"/api/pdf-import/source-pdfs/{source_id}/problems").json() == []

    root = f"/api/pdf-import/source-pdfs/{source_id}/crop-review"
    first = client.post(f"{root}/pages/1/prepare")
    assert first.status_code == 200, first.text
    page = first.json()["pages"][0]
    assert page["proposals"]
    assert page["image_width"] > 0
    assert client.get(page["proposals"][0]["preview_image_url"]).status_code == 200
    assert client.post(f"{root}/pages/1/prepare").json()["pages"][0]["version"] == 1

    old = page["proposals"][0]["id"]
    retried = client.post(f"{root}/pages/1/retry")
    assert retried.status_code == 200, retried.text
    assert retried.json()["pages"][0]["version"] == 2
    assert client.patch(f"/api/pdf-import/crop-proposals/{old}", json={"decision": "accepted"}).status_code == 409
    assert client.post(f"{root}/pages/1/confirm").status_code == 409

    for i, proposal in enumerate(retried.json()["pages"][0]["proposals"]):
        decision = "accepted" if i == 0 else "discarded"
        response = client.patch(f"/api/pdf-import/crop-proposals/{proposal['id']}",
                                json={"decision": decision})
        assert response.status_code == 200, response.text
    assert client.post(f"{root}/pages/1/confirm").status_code == 200

    blank = client.post(f"{root}/pages/2/prepare")
    assert blank.status_code == 200, blank.text
    assert blank.json()["pages"][1]["proposals"] == []
    assert client.post(f"{root}/pages/2/confirm").status_code == 200
    assert client.get(f"/api/pdf-import/source-pdfs/{source_id}/problems").json() == []

    final = client.post(f"{root}/finalize")
    assert final.status_code == 200, final.text
    assert final.json()["imported_problem_count"] == 1
    problems = client.get(f"/api/pdf-import/source-pdfs/{source_id}/problems").json()
    assert len(problems) == 1
    assert client.post(f"{root}/finalize").json()["imported_problem_count"] == 1


def test_gemini_replaces_whitespace_proposals_before_user_review(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    from app.services.gemini_page_crop_client import GeminiPageCropClient

    calls = []

    def inspect(_self, page_path, proposed):
        calls.append((page_path, proposed))
        return {"verdict": "replace", "reason": "Left column is a heading.",
                "boxes": [{"number": 1, "box_2d": [50, 510, 460, 950]}],
                "_usage": {"total_input_tokens": 101, "total_output_tokens": 17}}

    monkeypatch.setattr(GeminiPageCropClient, "inspect", inspect)
    path = _pdf(tmp_path)
    with path.open("rb") as stream:
        source_id = client.post("/api/pdf-import/review-uploads",
                                files={"file": ("review.pdf", stream, "application/pdf")}).json()["source_pdf_id"]
    result = client.post(f"/api/pdf-import/source-pdfs/{source_id}/crop-review/pages/1/prepare")
    assert result.status_code == 200, result.text
    page = result.json()["pages"][0]
    assert len(calls) == 1
    assert page["method"] == "gemini"
    assert page["input_tokens"] == 101
    assert len(page["proposals"]) == 1
    assert page["proposals"][0]["problem_number"] == 1
    assert page["proposals"][0]["decision"] == "pending"


def test_manual_crop_edit_add_and_batch_accept(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    path = _pdf(tmp_path)
    with path.open("rb") as stream:
        source_id = client.post("/api/pdf-import/review-uploads",
                                files={"file": ("review.pdf", stream, "application/pdf")}).json()["source_pdf_id"]
    root = f"/api/pdf-import/source-pdfs/{source_id}/crop-review"
    page = client.post(f"{root}/pages/1/prepare").json()["pages"][0]
    proposal = page["proposals"][0]
    original_url = proposal["preview_image_url"]
    box = {"x": 50, "y": 50, "width": 400, "height": 500}
    edited = client.patch(f"/api/pdf-import/crop-proposals/{proposal['id']}/box", json=box)
    assert edited.status_code == 200, edited.text
    edited_proposal = edited.json()["pages"][0]["proposals"][0]
    assert edited_proposal["crop_box"] == box
    assert edited_proposal["decision"] == "accepted"
    assert edited_proposal["origin"] == "manual"
    assert edited_proposal["preview_image_url"] != original_url
    assert client.get(edited_proposal["preview_image_url"]).status_code == 200
    with Image.open(tmp_path / "uploads" / edited_proposal["preview_image_url"].removeprefix("/uploads/")) as preview:
        assert preview.size == (400, 500)
    assert client.patch(f"/api/pdf-import/crop-proposals/{proposal['id']}/box",
                        json={"x": 99999, "y": 0, "width": 40, "height": 40}).status_code == 409

    added = client.post(f"{root}/pages/1/proposals", json={"x": 60, "y": 800, "width": 300, "height": 200})
    assert added.status_code == 200, added.text
    assert client.post(f"{root}/pages/1/proposals", json={"x": 60, "y": 800, "width": 300, "height": 200}).status_code == 409
    assert len(added.json()["pages"][0]["proposals"]) == len(page["proposals"]) + 1
    assert added.json()["pages"][0]["proposals"][-1]["decision"] == "accepted"
    accepted = client.post(f"{root}/pages/1/accept-all")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["pages"][0]["confirmed"] is True
    assert all(p["decision"] == "accepted" for p in accepted.json()["pages"][0]["proposals"])
    # A subsequent manual change must reopen page confirmation.
    again = client.patch(f"/api/pdf-import/crop-proposals/{proposal['id']}/box", json=box)
    assert again.json()["pages"][0]["confirmed"] is False
    assert client.post(f"{root}/pages/1/confirm").status_code == 200
    assert client.post(f"{root}/pages/2/prepare").status_code == 200
    assert client.post(f"{root}/pages/2/confirm").status_code == 200
    assert client.post(f"{root}/finalize").status_code == 200
    problems = client.get(f"/api/pdf-import/source-pdfs/{source_id}/problems").json()
    assert any(problem["crop_box"] == box for problem in problems)

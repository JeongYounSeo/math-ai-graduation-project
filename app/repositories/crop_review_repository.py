from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.crop_review import CropPageReview, CropProposal


class CropPageReviewRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, source_id: str, page_number: int):
        return self.db.query(CropPageReview).filter_by(source_pdf_id=source_id, page_number=page_number).first()

    def list(self, source_id: str):
        return self.db.query(CropPageReview).filter_by(source_pdf_id=source_id).order_by(CropPageReview.page_number).all()

    def prepare(self, source_id: str, page_number: int, *, method: str, verdict: str, reason: str, input_tokens: int, output_tokens: int):
        row = self.get(source_id, page_number)
        if row is None:
            row = CropPageReview(source_pdf_id=source_id, page_number=page_number)
            self.db.add(row)
        row.version = (row.version or 0) + 1
        row.status = "awaiting_review"
        row.confirmed = 0
        row.method = method
        row.verdict = verdict
        row.reason = reason
        row.input_tokens = input_tokens
        row.output_tokens = output_tokens
        self.db.flush()
        return row

    def confirm(self, row: CropPageReview):
        row.confirmed = 1
        row.status = "confirmed"
        self.db.commit()


class CropProposalRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, proposal_id: int):
        return self.db.query(CropProposal).filter_by(id=proposal_id).first()

    def list(self, source_id: str, page_number: int, version: int):
        rows = (self.db.query(CropProposal)
                .filter_by(source_pdf_id=source_id, page_number=page_number, version=version)
                .order_by(CropProposal.id).all())
        # Concurrent retries made identical rows in older review sessions.
        # Show/import one copy of the same pixel box.
        seen = set()
        distinct = []
        for row in rows:
            box = row.crop_box
            key = tuple(box[name] for name in ("x", "y", "width", "height"))
            if key not in seen:
                distinct.append(row)
                seen.add(key)
        return distinct

    def add(self, **fields):
        row = CropProposal(**fields)
        self.db.add(row)
        self.db.flush()
        return row

    def decide(self, row: CropProposal, decision: str):
        row.decision = decision
        row.decided_at = datetime.now(timezone.utc)
        self.db.commit()

    def accept_pending_page(self, source_id: str, page_number: int, version: int):
        rows = (self.db.query(CropProposal)
                .filter_by(source_pdf_id=source_id, page_number=page_number, version=version).all())
        for row in rows:
            if row.decision == "pending":
                row.decision = "accepted"
                row.decided_at = datetime.now(timezone.utc)
        self.db.flush()
        return rows

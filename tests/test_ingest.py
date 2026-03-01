"""Tests for the ingestion API endpoints.

Covered:
  POST /api/v1/sop/ingest           — upload a PDF document
  GET  /api/v1/sop/ingest/jobs/{id} — poll job status
"""

import io
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Minimal valid PDF — starts with the %PDF magic bytes.
_VALID_PDF = b"%PDF-1.4 minimal-content-for-testing"


def _stub_execute_first(db_mock, value):
    """Make db_mock.execute(…).scalars().first() return value."""
    result = MagicMock()
    result.scalars.return_value.first.return_value = value
    db_mock.execute.return_value = result


# ---------------------------------------------------------------------------
# POST /api/v1/sop/ingest
# ---------------------------------------------------------------------------


class TestIngestUpload:
    def test_valid_pdf_returns_202(self, client, db_mock):
        with patch.object(Path, "mkdir"), patch.object(Path, "write_bytes"):
            resp = client.post(
                "/api/v1/sop/ingest",
                files={"file": ("sop.pdf", io.BytesIO(_VALID_PDF), "application/pdf")},
            )

        assert resp.status_code == 202
        body = resp.json()
        assert "job_id" in body
        assert "document_id" in body
        assert body["status"] == "queued"

    def test_non_pdf_bytes_returns_400(self, client):
        # Correct extension, wrong magic bytes (PK = zip).
        resp = client.post(
            "/api/v1/sop/ingest",
            files={"file": ("doc.pdf", io.BytesIO(b"PK\x03\x04fake"), "application/pdf")},
        )
        assert resp.status_code == 400
        assert "PDF" in resp.json()["detail"]

    def test_oversized_file_returns_400(self, client):
        # 10 MB + 1 byte exceeds the hard limit.
        oversized = b"%PDF" + b"x" * (10 * 1024 * 1024 + 1)
        resp = client.post(
            "/api/v1/sop/ingest",
            files={"file": ("big.pdf", io.BytesIO(oversized), "application/pdf")},
        )
        assert resp.status_code == 400

    def test_missing_auth_rejected(self, no_auth_client):
        resp = no_auth_client.post(
            "/api/v1/sop/ingest",
            files={"file": ("sop.pdf", io.BytesIO(_VALID_PDF), "application/pdf")},
        )
        assert resp.status_code in (401, 403)

    def test_pdf_magic_bytes_checked_not_extension(self, client, db_mock):
        """Validation uses content magic bytes — not file extension."""
        with patch.object(Path, "mkdir"), patch.object(Path, "write_bytes"):
            resp = client.post(
                "/api/v1/sop/ingest",
                files={
                    "file": (
                        "report.bin",
                        io.BytesIO(_VALID_PDF),
                        "application/octet-stream",
                    )
                },
            )
        # Accepted — magic bytes are correct even though extension is .bin.
        assert resp.status_code == 202


# ---------------------------------------------------------------------------
# GET /api/v1/sop/ingest/jobs/{job_id}
# ---------------------------------------------------------------------------


class TestJobStatus:
    def test_known_job_returns_status(self, client, db_mock):
        job_id = uuid.uuid4()
        mock_job = MagicMock()
        mock_job.id = job_id
        mock_job.status.value = "queued"
        mock_job.document_id = uuid.uuid4()
        mock_job.error_message = None
        mock_job.completed_at = None
        _stub_execute_first(db_mock, mock_job)

        resp = client.get(f"/api/v1/sop/ingest/jobs/{job_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"

    def test_unknown_job_returns_404(self, client, db_mock):
        _stub_execute_first(db_mock, None)
        resp = client.get(f"/api/v1/sop/ingest/jobs/{uuid.uuid4()}")
        assert resp.status_code == 404

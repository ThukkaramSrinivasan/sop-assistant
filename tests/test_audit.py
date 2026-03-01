"""Tests for the audit response endpoint.

Covered:
  GET /api/v1/sop/responses/{response_id} — retrieve full audit record
"""

import datetime
import uuid
from unittest.mock import MagicMock

import pytest

_RESPONSE_ID = uuid.uuid4()


def _mock_ai_response() -> MagicMock:
    rec = MagicMock()
    rec.id = _RESPONSE_ID
    rec.customer_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    rec.response_text = "The protocol requires..."
    rec.prompt_sent = "System: You are an AI assistant that analyzes SOPs..."
    rec.retrieved_chunk_ids = []  # empty → second DB query is skipped
    rec.model_name = "claude-sonnet-4-20250514"
    rec.model_temperature = 0.0
    rec.latency_ms = 1240
    rec.created_at = datetime.datetime.utcnow()
    return rec


def _stub_execute_first(db_mock, value):
    result = MagicMock()
    result.scalars.return_value.first.return_value = value
    db_mock.execute.return_value = result


class TestAuditResponse:
    def test_existing_response_returns_audit_detail(self, client, db_mock):
        _stub_execute_first(db_mock, _mock_ai_response())
        resp = client.get(f"/api/v1/sop/responses/{_RESPONSE_ID}")

        assert resp.status_code == 200
        body = resp.json()
        assert "audit" in body
        assert "prompt_sent" in body["audit"]
        assert "retrieved_chunk_ids" in body["audit"]
        assert "latency_ms" in body["audit"]

    def test_cross_tenant_response_returns_404(self, client, db_mock):
        # The endpoint applies customer_id filter — a mismatch returns None,
        # which the endpoint treats identically to a missing record (404).
        _stub_execute_first(db_mock, None)
        resp = client.get(f"/api/v1/sop/responses/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_nonexistent_id_returns_404(self, client, db_mock):
        _stub_execute_first(db_mock, None)
        resp = client.get(f"/api/v1/sop/responses/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_missing_auth_rejected(self, no_auth_client):
        resp = no_auth_client.get(f"/api/v1/sop/responses/{uuid.uuid4()}")
        assert resp.status_code in (401, 403)

"""Tests for the RAG query API endpoints.

Covered:
  POST /api/v1/sop/query           — submit a query, receive a cited AI response
"""

import datetime
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.query import QueryResponse

_MOCK_RESPONSE = QueryResponse(
    response_id=uuid.uuid4(),
    answer="Based on the SOP, the correct procedure is...",
    sources_relevant=True,
    sources=[],
    model="claude-sonnet-4-20250514",
    generated_at=datetime.datetime.utcnow(),
)


class TestQuery:
    def test_valid_query_returns_200(self, client):
        with patch("app.api.v1.query.generate", AsyncMock(return_value=_MOCK_RESPONSE)):
            resp = client.post(
                "/api/v1/sop/query",
                json={"query": "What is the ICU medication protocol?"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "answer" in body
        assert "response_id" in body

    def test_missing_query_field_returns_422(self, client):
        resp = client.post("/api/v1/sop/query", json={})
        assert resp.status_code == 422

    def test_empty_query_string_returns_422(self, client):
        # QueryRequest enforces min_length=1.
        resp = client.post("/api/v1/sop/query", json={"query": ""})
        assert resp.status_code == 422

    def test_missing_auth_rejected(self, no_auth_client):
        resp = no_auth_client.post(
            "/api/v1/sop/query",
            json={"query": "What is the protocol?"},
        )
        assert resp.status_code in (401, 403)

    def test_sources_relevant_present_in_response(self, client):
        with patch("app.api.v1.query.generate", AsyncMock(return_value=_MOCK_RESPONSE)):
            resp = client.post(
                "/api/v1/sop/query",
                json={"query": "What is the protocol?"},
            )

        assert resp.status_code == 200
        assert "sources_relevant" in resp.json()

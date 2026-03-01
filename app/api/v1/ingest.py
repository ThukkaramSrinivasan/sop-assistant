"""
Ingest API endpoints — implemented in Phase 2.

POST /sop/ingest          — upload PDF, enqueue ingestion job
GET  /sop/ingest/jobs/{id} — poll job status
"""

from fastapi import APIRouter

router = APIRouter()

# Phase 2 implementation

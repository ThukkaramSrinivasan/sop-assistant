from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class IngestResponse(BaseModel):
    """Returned immediately after a PDF upload — before processing starts."""

    job_id: UUID
    document_id: UUID
    status: str  # always "queued" at creation time


class JobStatusResponse(BaseModel):
    """Returned by GET /sop/ingest/jobs/{job_id}."""

    job_id: UUID
    status: str
    document_id: UUID
    error_message: Optional[str] = None
    completed_at: Optional[datetime] = None

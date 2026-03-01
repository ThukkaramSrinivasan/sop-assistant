from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.query import SourceCitation


class AuditDetail(BaseModel):
    """Full audit metadata — only exposed via the audit endpoint, not the query response."""

    prompt_sent: str  # full prompt verbatim
    retrieved_chunk_ids: list[UUID]
    latency_ms: int
    model_temperature: float


class AuditResponse(BaseModel):
    """Returned by GET /sop/responses/{id} — full audit trail."""

    response_id: UUID
    answer: str
    sources: list[SourceCitation]
    model: str
    generated_at: datetime
    audit: AuditDetail

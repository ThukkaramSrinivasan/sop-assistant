from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    # Optional: scope retrieval to specific documents within the customer's tenant
    document_ids: Optional[list[UUID]] = None


class SourceCitation(BaseModel):
    """A single retrieved chunk that contributed to the AI answer."""

    chunk_id: UUID
    document_filename: str
    chunk_index: int
    relevance_score: float


class QueryResponse(BaseModel):
    """Returned by POST /sop/query."""

    response_id: UUID
    answer: str
    sources: list[SourceCitation]
    model: str
    generated_at: datetime

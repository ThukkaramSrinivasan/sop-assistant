from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    # Optional: scope retrieval to specific documents within the customer's tenant
    document_ids: Optional[list[UUID]] = None
    # Optional: pass conversation_id from a previous turn to continue a session
    conversation_id: Optional[UUID] = None
    # Optional: prior messages for context — server caps at last 6 before sending to LLM
    conversation_history: Optional[list[ConversationMessage]] = []


class SourceCitation(BaseModel):
    """A single retrieved chunk that contributed to the AI answer."""

    chunk_id: UUID
    document_filename: str
    chunk_index: int
    relevance_score: float
    page_number: Optional[int] = None
    chunk_text: str


class QueryResponse(BaseModel):
    """Returned by POST /sop/query."""

    response_id: UUID
    answer: str
    sources_relevant: bool
    sources: list[SourceCitation]
    model: str
    generated_at: datetime
    # Returned so the frontend can pass it back on the next turn
    conversation_id: UUID

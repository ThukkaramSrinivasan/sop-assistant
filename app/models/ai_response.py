from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Column, Index
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, SQLModel


class AIResponse(SQLModel, table=True):
    __tablename__ = "ai_responses"
    __table_args__ = (Index("ix_ai_responses_customer_id", "customer_id"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    customer_id: UUID = Field(nullable=False)
    query_text: str = Field(nullable=False)
    # Full prompt sent to the LLM — verbatim, required for auditability
    prompt_sent: str = Field(nullable=False)
    # Exact chunk IDs used as context — required for auditability
    retrieved_chunk_ids: list = Field(
        sa_column=Column(ARRAY(PGUUID(as_uuid=True)), nullable=False)
    )
    model_name: str = Field(max_length=100, nullable=False)
    # Always 0 — stored for auditability, confirms deterministic generation
    model_temperature: float = Field(nullable=False)
    response_text: str = Field(nullable=False)
    confidence_score: Optional[float] = Field(default=None)
    latency_ms: int = Field(nullable=False)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    # customer_id of the requesting user (same as customer_id in this model)
    created_by: UUID = Field(nullable=False)
    # AI response records are NEVER deleted — they are the audit trail

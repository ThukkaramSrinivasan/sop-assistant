from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Index
from sqlmodel import Field, SQLModel


class DocumentChunk(SQLModel, table=True):
    __tablename__ = "document_chunks"
    __table_args__ = (
        Index("ix_document_chunks_customer_id", "customer_id"),
        Index("ix_document_chunks_document_id", "document_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    document_id: UUID = Field(nullable=False, foreign_key="documents.id")
    # Denormalized customer_id — enables efficient tenant-scoped queries without joins
    customer_id: UUID = Field(nullable=False)
    chunk_index: int = Field(nullable=False)
    chunk_text: str = Field(nullable=False)
    token_count: int = Field(nullable=False)
    # vector(1536) via pgvector — internal, never exposed via API
    embedding: Optional[list] = Field(
        default=None,
        sa_column=Column(Vector(1536), nullable=True),
    )
    # Track which model produced this embedding (for future model migrations)
    embedding_model: Optional[str] = Field(default=None, max_length=100)
    # Soft delete — never hard-delete chunks
    is_active: bool = Field(default=True, nullable=False)
    embedded_at: Optional[datetime] = Field(default=None)

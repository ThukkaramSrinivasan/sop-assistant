"""RAG retriever — embed the query and search pgvector for similar chunks.

Two public functions:
  embed_query      — embed query text using text-embedding-3-small (same model as ingestion)
  retrieve_chunks  — cosine similarity search with mandatory customer_id filter
"""

import logging
from dataclasses import dataclass
from uuid import UUID

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.chunk import DocumentChunk
from app.models.document import Document

logger = logging.getLogger(__name__)

# Module-level singleton — shares the HTTP connection pool across calls.
_openai: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _openai
    if _openai is None:
        _openai = AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai


@dataclass
class RetrievedChunk:
    chunk_id: UUID
    chunk_text: str
    document_filename: str
    chunk_index: int
    similarity_score: float


async def embed_query(query_text: str) -> list[float]:
    """Embed the user query using the same model used at ingestion time.

    Using the same model is critical — vectors must live in the same space
    for cosine similarity to be meaningful.
    """
    client = _get_client()
    response = await client.embeddings.create(
        model=settings.embedding_model,
        input=query_text,
    )
    return response.data[0].embedding


async def retrieve_chunks(
    query_embedding: list[float],
    customer_id: UUID,
    db: AsyncSession,
    document_ids: list[UUID] | None = None,
    top_k: int = 5,
) -> list[RetrievedChunk]:
    """Search pgvector for the top-k chunks most similar to query_embedding.

    customer_id filter is mandatory and never omitted — cross-tenant data leakage
    is the worst failure mode for a multi-tenant system.

    document_ids scopes the search to a subset of the customer's documents when
    the caller wants to ask questions about specific SOPs rather than all of them.
    """
    distance_expr = DocumentChunk.embedding.cosine_distance(query_embedding)

    conditions = [
        DocumentChunk.customer_id == customer_id,
        DocumentChunk.is_active.is_(True),
        Document.is_active.is_(True),
    ]
    if document_ids:
        conditions.append(DocumentChunk.document_id.in_(document_ids))

    stmt = (
        select(
            DocumentChunk.id,
            DocumentChunk.chunk_text,
            DocumentChunk.chunk_index,
            Document.filename,
            (1 - distance_expr).label("similarity"),
        )
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(*conditions)
        .order_by(distance_expr)
        .limit(top_k)
    )

    result = await db.execute(stmt)
    rows = result.all()

    logger.debug(
        "Retrieved %d chunks for customer=%s (top_k=%d)", len(rows), customer_id, top_k
    )

    return [
        RetrievedChunk(
            chunk_id=row.id,
            chunk_text=row.chunk_text,
            document_filename=row.filename,
            chunk_index=row.chunk_index,
            similarity_score=float(row.similarity),
        )
        for row in rows
    ]

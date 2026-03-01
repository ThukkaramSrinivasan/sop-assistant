"""OpenAI embedding calls and chunk persistence.

Three public functions:
  should_skip_ingestion — dedup check: has this file_hash already been embedded?
  embed_chunks          — call OpenAI in batches of ≤100, return vectors
  upsert_chunks         — write DocumentChunk rows with embeddings to the DB
"""

import logging
from datetime import datetime, timezone
from uuid import UUID

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.chunk import DocumentChunk
from app.models.document import Document, DocumentStatus
from app.services.ingestion.chunker import ChunkData

logger = logging.getLogger(__name__)

_EMBED_BATCH_SIZE = 100  # OpenAI hard-limit is 2048 inputs; we use 100 for safety

# Module-level singleton — avoids rebuilding the HTTP client on every call.
_openai: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _openai
    if _openai is None:
        _openai = AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai


async def should_skip_ingestion(
    file_hash: str,
    customer_id: UUID,
    db: AsyncSession,
) -> bool:
    """Return True if this customer already has a completed document with the same SHA-256 hash.

    Used to avoid re-embedding identical PDF content (e.g. duplicate uploads).
    The customer_id filter ensures we never read across tenant boundaries.
    """
    result = await db.execute(
        select(Document)
        .where(
            Document.customer_id == customer_id,
            Document.file_hash == file_hash,
            Document.status == DocumentStatus.completed,
            Document.is_active.is_(True),
        )
        .limit(1)
    )
    return result.scalars().first() is not None


async def embed_chunks(chunks: list[ChunkData]) -> list[list[float]]:
    """Embed a list of chunks using OpenAI, batching into groups of ≤100.

    The order of the returned vectors matches the order of *chunks*.
    """
    client = _get_client()
    all_embeddings: list[list[float]] = []

    for batch_start in range(0, len(chunks), _EMBED_BATCH_SIZE):
        batch = chunks[batch_start : batch_start + _EMBED_BATCH_SIZE]
        texts = [c.chunk_text for c in batch]

        response = await client.embeddings.create(
            model=settings.embedding_model,
            input=texts,
        )

        # Sort by index to guarantee input order (defensive — OpenAI preserves order).
        ordered = sorted(response.data, key=lambda item: item.index)
        all_embeddings.extend(item.embedding for item in ordered)

        logger.debug(
            "Embedded batch %d–%d (%d vectors)",
            batch_start,
            batch_start + len(batch) - 1,
            len(batch),
        )

    return all_embeddings


async def upsert_chunks(
    document_id: UUID,
    customer_id: UUID,
    chunks: list[ChunkData],
    embeddings: list[list[float]],
    db: AsyncSession,
) -> None:
    """Persist DocumentChunk rows with embeddings.

    Soft-deletes any pre-existing active chunks for this document before
    inserting, so a retried ingestion job never produces duplicate rows.
    """
    # Soft-delete any chunks from a previous (partial) attempt on this document.
    existing = await db.execute(
        select(DocumentChunk).where(
            DocumentChunk.document_id == document_id,
            DocumentChunk.is_active.is_(True),
        )
    )
    for old_chunk in existing.scalars().all():
        old_chunk.is_active = False

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for chunk, embedding in zip(chunks, embeddings):
        db.add(
            DocumentChunk(
                document_id=document_id,
                customer_id=customer_id,
                chunk_index=chunk.chunk_index,
                page_number=chunk.page_number,
                chunk_text=chunk.chunk_text,
                token_count=chunk.token_count,
                embedding=embedding,
                embedding_model=settings.embedding_model,
                is_active=True,
                embedded_at=now,
            )
        )

    await db.commit()
    logger.info("Upserted %d chunks for document %s", len(chunks), document_id)

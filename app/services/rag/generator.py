"""RAG generator — orchestrates retrieve → prompt → LLM → audit storage.

Single public function:
  generate — runs the full RAG pipeline and returns a QueryResponse schema object.

The complete audit record (prompt verbatim, chunk IDs, latency, model params) is
written to ai_responses before this function returns. Records are never deleted.
"""

import logging
import time
from uuid import UUID, uuid4

import anthropic
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.ai_response import AIResponse
from app.schemas.query import QueryResponse, SourceCitation
from app.services.rag.prompt import build_prompt
from app.services.rag.retriever import RetrievedChunk, embed_query, retrieve_chunks

logger = logging.getLogger(__name__)

# Module-level singleton — avoids rebuilding the HTTP client on every request.
_anthropic: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _anthropic
    if _anthropic is None:
        _anthropic = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _anthropic


async def generate(
    query: str,
    customer_id: UUID,
    created_by: UUID,
    db: AsyncSession,
    document_ids: list[UUID] | None = None,
    conversation_id: UUID | None = None,
    conversation_history: list | None = None,
) -> QueryResponse:
    """Run the full RAG pipeline for a single query.

    Steps:
      1. Resolve conversation_id (generate new UUID if first turn).
      2. Embed the query (same model as ingestion — vectors must share a space).
      3. Retrieve top-k chunks from pgvector, filtered by customer_id.
      4. Build the prompt from retrieved context (+ conversation history if present).
      5. Call the Anthropic LLM (temperature=0 for deterministic, auditable output).
      6. Persist the complete audit record to ai_responses.
      7. Map to QueryResponse schema — never return the DB model directly.
    """
    # 1. Resolve conversation context.
    #    Generate a new conversation_id if this is the first turn.
    if conversation_id is None:
        conversation_id = uuid4()

    # Count existing turns so we can assign a sequential turn_number.
    count_result = await db.execute(
        select(func.count()).select_from(AIResponse).where(
            AIResponse.conversation_id == conversation_id
        )
    )
    turn_number = (count_result.scalar() or 0) + 1

    # Convert ConversationMessage objects to plain dicts for JSON storage
    # and for the prompt builder (which accepts either dicts or objects).
    history_dicts = [
        (m.model_dump() if hasattr(m, "model_dump") else m)
        for m in (conversation_history or [])
    ]

    # 2. Embed query.
    query_embedding = await embed_query(query)

    # 3. Retrieve chunks — customer_id filter is mandatory.
    chunks = await retrieve_chunks(
        query_embedding=query_embedding,
        customer_id=customer_id,
        db=db,
        document_ids=document_ids,
        top_k=settings.rag_top_k,
    )

    # 4. Build full prompt (stored verbatim for auditability).
    prompt = build_prompt(query, chunks, conversation_history=history_dicts or None)

    # 4. Call Anthropic — temperature=0 required for regulated-domain auditability.
    client = _get_client()
    t0 = time.monotonic()
    response = await client.messages.create(
        model=settings.llm_model,
        max_tokens=2048,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    latency_ms = int((time.monotonic() - t0) * 1000)
    raw_answer = response.content[0].text

    # Parse and strip the SOURCES_USED marker the LLM appends per prompt instructions.
    # Default to True so old responses (or parse failures) always show sources.
    sources_relevant: bool = True
    lines = raw_answer.strip().splitlines()
    last_line = lines[-1].strip() if lines else ""
    logger.info("[DEBUG] SOURCES_USED parse — last_line=%r", last_line)
    if lines and last_line.startswith("SOURCES_USED:"):
        marker_value = last_line.split(":", 1)[1].strip().lower()
        sources_relevant = marker_value == "true"
        answer = "\n".join(lines[:-1]).strip()
    else:
        answer = raw_answer.strip()
    logger.info(
        "[DEBUG] SOURCES_USED parse — sources_relevant=%s answer_preview=%r",
        sources_relevant,
        answer[:120],
    )

    logger.info(
        "LLM response generated: customer=%s chunks=%d latency_ms=%d model=%s",
        customer_id,
        len(chunks),
        latency_ms,
        settings.llm_model,
    )

    # 5. Persist audit record — never deleted, required for regulated-domain compliance.
    record = AIResponse(
        customer_id=customer_id,
        query_text=query,
        prompt_sent=prompt,
        retrieved_chunk_ids=[chunk.chunk_id for chunk in chunks],
        model_name=settings.llm_model,
        model_temperature=0.0,
        response_text=answer,
        sources_relevant=sources_relevant,
        confidence_score=chunks[0].similarity_score if chunks else None,
        latency_ms=latency_ms,
        created_by=created_by,
        conversation_id=conversation_id,
        turn_number=turn_number,
        conversation_history=history_dicts if history_dicts else None,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    # 6. Map to API schema — DB model never leaves this function.
    return QueryResponse(
        response_id=record.id,
        answer=answer,
        sources_relevant=sources_relevant,
        sources=[
            SourceCitation(
                chunk_id=chunk.chunk_id,
                document_filename=chunk.document_filename,
                chunk_index=chunk.chunk_index,
                relevance_score=chunk.similarity_score,
                page_number=chunk.page_number,
                chunk_text=chunk.chunk_text,
            )
            for chunk in chunks
        ],
        model=settings.llm_model,
        generated_at=record.created_at,
        conversation_id=conversation_id,
    )

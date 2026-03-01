"""Query API endpoints.

POST /sop/query          — submit a RAG query, receive a cited AI response
GET  /sop/responses/{id} — retrieve the full audit record for a past response

customer_id is extracted from the JWT only — never from the request body.
The LLM call is made synchronously within the HTTP request (no separate worker)
because query latency (~1-3s) is acceptable and simplifies the response contract.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_customer_id
from app.models.ai_response import AIResponse
from app.models.chunk import DocumentChunk
from app.models.document import Document
from app.schemas.audit import AuditDetail, AuditResponse
from app.schemas.query import QueryRequest, QueryResponse, SourceCitation
from app.services.rag.generator import generate

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# POST /sop/query
# ---------------------------------------------------------------------------


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Submit a RAG query against ingested SOPs",
)
async def query_documents(
    body: QueryRequest,
    customer_id: UUID = Depends(get_current_customer_id),
    db: AsyncSession = Depends(get_db),
) -> QueryResponse:
    """Embed the query, retrieve the most relevant SOP chunks, and generate a
    cited AI answer.

    The full audit record (prompt, chunk IDs, latency, model params) is stored
    automatically before the response is returned.
    """
    return await generate(
        query=body.query,
        customer_id=customer_id,
        created_by=customer_id,
        document_ids=body.document_ids,
        db=db,
    )


# ---------------------------------------------------------------------------
# GET /sop/responses/{response_id}
# ---------------------------------------------------------------------------


@router.get(
    "/responses/{response_id}",
    response_model=AuditResponse,
    summary="Retrieve the full audit record for a past AI response",
)
async def get_response(
    response_id: UUID,
    customer_id: UUID = Depends(get_current_customer_id),
    db: AsyncSession = Depends(get_db),
) -> AuditResponse:
    """Return the complete audit trail for a stored AI response.

    Includes the verbatim prompt sent to the LLM, retrieved chunk IDs, latency,
    and model parameters.  The customer_id from the JWT must match the response's
    customer_id — cross-tenant access returns 404 (same as not found) to avoid
    leaking the existence of another tenant's data.
    """
    result = await db.execute(
        select(AIResponse).where(
            AIResponse.id == response_id,
            AIResponse.customer_id == customer_id,  # tenant isolation
        )
    )
    record = result.scalars().first()

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Response not found",
        )

    # Reconstruct source citations by joining back to chunks + documents.
    # Relevance scores are not persisted in the audit record (known limitation —
    # a future JSONB column on ai_responses would preserve them).
    chunk_ids = record.retrieved_chunk_ids or []
    sources: list[SourceCitation] = []

    if chunk_ids:
        chunks_result = await db.execute(
            select(
                DocumentChunk.id,
                DocumentChunk.chunk_index,
                Document.filename,
            )
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                DocumentChunk.id.in_(chunk_ids),
                DocumentChunk.customer_id == customer_id,  # defense in depth
            )
        )
        chunk_map = {row.id: row for row in chunks_result.all()}

        # Preserve original retrieval order stored in retrieved_chunk_ids.
        sources = [
            SourceCitation(
                chunk_id=cid,
                document_filename=chunk_map[cid].filename,
                chunk_index=chunk_map[cid].chunk_index,
                relevance_score=0.0,  # not stored; see note above
            )
            for cid in chunk_ids
            if cid in chunk_map
        ]

    return AuditResponse(
        response_id=record.id,
        answer=record.response_text,
        sources=sources,
        model=record.model_name,
        generated_at=record.created_at,
        audit=AuditDetail(
            prompt_sent=record.prompt_sent,
            retrieved_chunk_ids=chunk_ids,
            latency_ms=record.latency_ms,
            model_temperature=record.model_temperature,
        ),
    )

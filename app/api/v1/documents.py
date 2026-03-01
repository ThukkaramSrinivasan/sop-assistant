"""Documents list endpoint.

GET /api/v1/sop/documents — list all active documents for the authenticated customer.

customer_id comes from the JWT only — never from the request body.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_customer_id
from app.models.document import Document
from app.schemas.document import DocumentListItem

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/documents",
    response_model=list[DocumentListItem],
    summary="List all documents for the authenticated customer",
)
async def list_documents(
    customer_id: UUID = Depends(get_current_customer_id),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentListItem]:
    """Return active documents for the authenticated customer, newest first.

    Internal fields (file_hash, is_active, embedding) are deliberately excluded
    from the response schema.
    """
    result = await db.execute(
        select(Document)
        .where(
            Document.customer_id == customer_id,
            Document.is_active.is_(True),
        )
        .order_by(Document.created_at.desc())
    )
    documents = result.scalars().all()

    return [
        DocumentListItem(
            document_id=doc.id,
            filename=doc.filename,
            status=doc.status.value,
            version=doc.version,
            created_at=doc.created_at,
        )
        for doc in documents
    ]

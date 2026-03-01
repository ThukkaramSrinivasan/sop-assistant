from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class DocumentListItem(BaseModel):
    """One row in GET /api/v1/sop/documents.

    Deliberately excludes file_hash and is_active — internal DB fields
    that must never be exposed to API consumers.
    """

    document_id: UUID
    filename: str
    status: str  # pending | processing | completed | failed
    version: int
    created_at: datetime

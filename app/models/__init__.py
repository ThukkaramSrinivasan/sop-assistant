"""
DB models — SQLModel classes with table=True.

These are the internal storage layer. Never return DB model instances
directly from API endpoints — always map to a schema in app/schemas/.
"""

from app.models.ai_response import AIResponse
from app.models.chunk import DocumentChunk
from app.models.customer import Customer
from app.models.document import Document, DocumentStatus
from app.models.ingestion_job import IngestionJob, JobStatus

__all__ = [
    "AIResponse",
    "Customer",
    "Document",
    "DocumentChunk",
    "DocumentStatus",
    "IngestionJob",
    "JobStatus",
]

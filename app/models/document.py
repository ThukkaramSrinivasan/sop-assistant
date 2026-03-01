import enum
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Column, Enum as SAEnum, Index
from sqlmodel import Field, SQLModel


class DocumentStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class Document(SQLModel, table=True):
    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_customer_id", "customer_id"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    customer_id: UUID = Field(nullable=False)
    filename: str = Field(max_length=512, nullable=False)
    # SHA-256 hex digest — used to detect duplicate uploads, never exposed via API
    file_hash: str = Field(max_length=64, nullable=False)
    status: DocumentStatus = Field(
        default=DocumentStatus.pending,
        sa_column=Column(
            SAEnum(DocumentStatus, name="documentstatus", create_type=False),
            nullable=False,
        ),
    )
    version: int = Field(default=1, nullable=False)
    # Soft delete — never hard-delete documents
    is_active: bool = Field(default=True, nullable=False)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)

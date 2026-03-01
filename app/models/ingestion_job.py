import enum
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Column, Enum as SAEnum, Index
from sqlmodel import Field, SQLModel


class JobStatus(str, enum.Enum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class IngestionJob(SQLModel, table=True):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        Index("ix_ingestion_jobs_customer_id", "customer_id"),
        # Composite index optimises the worker's FOR UPDATE SKIP LOCKED poll query
        Index("ix_ingestion_jobs_status_enqueued_at", "status", "enqueued_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    document_id: UUID = Field(nullable=False, foreign_key="documents.id")
    customer_id: UUID = Field(nullable=False)
    status: JobStatus = Field(
        default=JobStatus.queued,
        sa_column=Column(
            SAEnum(JobStatus, name="jobstatus", create_type=False),
            nullable=False,
        ),
    )
    error_message: Optional[str] = Field(default=None)
    enqueued_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    started_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)

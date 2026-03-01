"""Ingest API endpoints.

POST /sop/ingest              — multipart PDF upload → 202 Accepted
GET  /sop/ingest/jobs/{id}    — poll job status

customer_id is extracted from the JWT only — never from the request body.
The heavy work (parse / chunk / embed) is never done here; it is enqueued
for the worker process (Process 2) to handle asynchronously.
"""

import hashlib
import logging
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_customer_id
from app.models.document import Document, DocumentStatus
from app.models.ingestion_job import IngestionJob, JobStatus
from app.schemas.ingest import IngestResponse, JobStatusResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# Must match the path used in the worker.
UPLOAD_DIR = Path("uploads")

_PDF_MAGIC = b"%PDF"
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


# ---------------------------------------------------------------------------
# POST /sop/ingest
# ---------------------------------------------------------------------------


@router.post(
    "/ingest",
    response_model=IngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a PDF for ingestion",
)
async def ingest_document(
    file: UploadFile = File(..., description="PDF file to ingest (max 10 MB)"),
    customer_id: UUID = Depends(get_current_customer_id),
    db: AsyncSession = Depends(get_db),
) -> IngestResponse:
    """Accept a PDF upload, persist the document record, and enqueue an ingestion job.

    Returns immediately with HTTP 202.  The actual parse/chunk/embed work is
    performed asynchronously by the ingestion worker process.
    """
    # --- Read and validate file -----------------------------------------------
    contents = await file.read()

    if len(contents) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit",
        )

    if contents[:4] != _PDF_MAGIC:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File must be a PDF (invalid file signature)",
        )

    # --- Compute SHA-256 for dedup (stored internally, never returned) --------
    file_hash = hashlib.sha256(contents).hexdigest()
    original_filename = file.filename or "document.pdf"

    # --- Persist document record and save file to disk ------------------------
    document_id = uuid4()

    upload_path = UPLOAD_DIR / str(customer_id)
    upload_path.mkdir(parents=True, exist_ok=True)
    file_path = upload_path / f"{document_id}.pdf"
    file_path.write_bytes(contents)

    document = Document(
        id=document_id,
        customer_id=customer_id,
        filename=original_filename,
        file_hash=file_hash,
        status=DocumentStatus.pending,
    )
    db.add(document)

    # --- Enqueue the ingestion job --------------------------------------------
    job = IngestionJob(
        document_id=document_id,
        customer_id=customer_id,
        status=JobStatus.queued,
    )
    db.add(job)
    await db.commit()

    logger.info(
        "Enqueued ingestion job=%s document=%s customer=%s filename=%r",
        job.id,
        document_id,
        customer_id,
        original_filename,
    )

    return IngestResponse(
        job_id=job.id,
        document_id=document_id,
        status=JobStatus.queued.value,
    )


# ---------------------------------------------------------------------------
# GET /sop/ingest/jobs/{job_id}
# ---------------------------------------------------------------------------


@router.get(
    "/ingest/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Poll the status of an ingestion job",
)
async def get_job_status(
    job_id: UUID,
    customer_id: UUID = Depends(get_current_customer_id),
    db: AsyncSession = Depends(get_db),
) -> JobStatusResponse:
    """Return the current status of an ingestion job.

    The customer_id from the JWT must match the job's customer_id —
    a customer cannot query another tenant's jobs.
    """
    result = await db.execute(
        select(IngestionJob).where(
            IngestionJob.id == job_id,
            IngestionJob.customer_id == customer_id,  # tenant isolation
        )
    )
    job = result.scalars().first()

    if job is None:
        # Return 404 for both "not found" and "belongs to another tenant" —
        # do not reveal the existence of another tenant's jobs.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    return JobStatusResponse(
        job_id=job.id,
        status=job.status.value,
        document_id=job.document_id,
        error_message=job.error_message,
        completed_at=job.completed_at,
    )

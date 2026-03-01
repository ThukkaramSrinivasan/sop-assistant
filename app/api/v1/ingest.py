"""Ingest API endpoints.

POST /sop/ingest              — multipart PDF upload → 202 Accepted
GET  /sop/ingest/jobs/{id}    — poll job status

customer_id is extracted from the JWT only — never from the request body.
The heavy work (parse / chunk / embed) is never done here; it is enqueued
for the ingestion worker service to handle asynchronously.
"""

# FILE STORAGE — KNOWN LIMITATION
# Current implementation saves PDFs to a local Docker volume (uploads/).
# This works for development but does not scale to production requirements:
# - 200 PDFs × 5MB × 1000 customers ≈ 1TB total storage
# - Local disk cannot be shared across horizontally scaled API instances
# - No redundancy — disk failure means data loss
#
# Production approach: stream uploads directly to object storage (AWS S3 / GCS)
# API stores the S3 key in the DB, worker downloads from S3 at processing time.
# This decouples file storage from compute, scales infinitely, and costs ~$23/month for 1TB.

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
# In production this should be replaced with object storage (S3/GCS) — the API
# uploads to the bucket, the worker downloads from it using the key stored in
# the DB.  Local disk storage only works when API and worker share a filesystem.
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
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File exceeds the {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit",
        )

    if contents[:4] != _PDF_MAGIC:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a PDF (invalid file signature)",
        )

    # --- Compute SHA-256 for dedup (stored internally, never returned) --------
    file_hash = hashlib.sha256(contents).hexdigest()
    original_filename = file.filename or "document.pdf"

    # --- Version lookup: is this an update to an existing document? -----------
    # Find the most recent active document with the same filename for this
    # customer.  If one exists this is a document update — bump the version and
    # soft-delete the old record so it no longer appears as the active copy.
    prev_result = await db.execute(
        select(Document)
        .where(
            Document.customer_id == customer_id,
            Document.filename == original_filename,
            Document.is_active.is_(True),
        )
        .order_by(Document.version.desc())
        .limit(1)
    )
    prev_doc = prev_result.scalars().first()

    if prev_doc is not None:
        new_version = prev_doc.version + 1
        prev_doc.is_active = False
        logger.info(
            "Versioning: %r v%d (document=%s) superseded — creating v%d",
            original_filename,
            prev_doc.version,
            prev_doc.id,
            new_version,
        )
    else:
        new_version = 1

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
        version=new_version,
    )
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

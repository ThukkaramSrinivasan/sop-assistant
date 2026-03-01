"""Ingestion worker — Process 2.

Runs as a standalone async process entirely separate from the FastAPI server.
Polls the ingestion_jobs table for queued work, processes each job (parse →
chunk → embed → store), and sleeps when the queue is empty.

Job claiming uses FOR UPDATE SKIP LOCKED so multiple worker instances can run
concurrently without double-processing a job.

Run with:
    python -m app.workers.ingestion_worker
"""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.document import Document, DocumentStatus
from app.models.ingestion_job import IngestionJob, JobStatus
from app.services.ingestion.chunker import chunk_text
from app.services.ingestion.embedder import embed_chunks, should_skip_ingestion, upsert_chunks
from app.services.ingestion.parser import PDFParseError, extract_text_from_pdf

logger = logging.getLogger(__name__)

# Must match the path used by the ingest API endpoint.
UPLOAD_DIR = Path("uploads")


# ---------------------------------------------------------------------------
# Job claiming
# ---------------------------------------------------------------------------


async def claim_next_job(db: AsyncSession) -> IngestionJob | None:
    """Atomically claim the oldest queued job.

    Uses SELECT … FOR UPDATE SKIP LOCKED so that concurrent worker processes
    each get a different job with no possibility of double-processing.
    Returns None if the queue is empty.
    """
    result = await db.execute(
        select(IngestionJob)
        .where(IngestionJob.status == JobStatus.queued)
        .order_by(IngestionJob.enqueued_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = result.scalars().first()
    if job is None:
        return None

    job.status = JobStatus.processing
    job.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    return job


# ---------------------------------------------------------------------------
# Job processing
# ---------------------------------------------------------------------------


async def process_job(job: IngestionJob, db: AsyncSession) -> None:
    """Orchestrate parse → chunk → embed → store for a single job.

    All DB mutations go through the provided session.  If anything raises, the
    caller's error handler will record the failure in a fresh session.
    """
    # 1. Load the associated document (customer_id filter is defence in depth).
    doc_result = await db.execute(
        select(Document).where(
            Document.id == job.document_id,
            Document.customer_id == job.customer_id,
        )
    )
    document = doc_result.scalars().first()
    if document is None:
        raise ValueError(
            f"Document {job.document_id} not found for customer {job.customer_id}"
        )

    # 2. Dedup check — skip heavy work if identical content was already embedded.
    if await should_skip_ingestion(document.file_hash, document.customer_id, db):
        logger.info(
            "Skipping re-ingestion: identical content already embedded "
            "(document=%s customer=%s hash=%s)",
            document.id,
            document.customer_id,
            document.file_hash,
        )
        document.status = DocumentStatus.completed
        job.status = JobStatus.completed
        job.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await db.commit()
        return

    # 3. Mark document as in-progress.
    document.status = DocumentStatus.processing
    await db.commit()

    # 4. Parse.
    filepath = str(UPLOAD_DIR / str(document.customer_id) / f"{document.id}.pdf")
    text = extract_text_from_pdf(filepath)  # raises PDFParseError on failure

    # 5. Chunk.
    chunks = chunk_text(text, settings.chunk_size_tokens, settings.chunk_overlap_tokens)
    if not chunks:
        raise ValueError(f"PDF '{document.filename}' produced no text chunks after parsing")

    # 6. Embed (batched OpenAI calls) and persist.
    embeddings = await embed_chunks(chunks)
    await upsert_chunks(document.id, document.customer_id, chunks, embeddings, db)

    # 7. Mark complete.
    document.status = DocumentStatus.completed
    job.status = JobStatus.completed
    job.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()

    logger.info(
        "Job %s completed: document=%s customer=%s chunks=%d",
        job.id,
        document.id,
        document.customer_id,
        len(chunks),
    )


# ---------------------------------------------------------------------------
# Failure recording
# ---------------------------------------------------------------------------


async def _mark_job_failed(job_id: UUID, document_id: UUID, error: str) -> None:
    """Record a job failure in a fresh session.

    The session used by claim_next_job/process_job may be in a broken state
    after an exception, so we always open a new session here.
    """
    try:
        async with AsyncSessionLocal() as db:
            job_result = await db.execute(
                select(IngestionJob).where(IngestionJob.id == job_id)
            )
            job = job_result.scalars().first()
            if job:
                job.status = JobStatus.failed
                job.error_message = error[:2000]  # guard against very long tracebacks
                job.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)

            doc_result = await db.execute(
                select(Document).where(Document.id == document_id)
            )
            document = doc_result.scalars().first()
            if document:
                document.status = DocumentStatus.failed

            await db.commit()
    except Exception as exc:
        # Failure-to-record-failure — log and move on; don't crash the loop.
        logger.exception("Could not record failure for job %s: %s", job_id, exc)


# ---------------------------------------------------------------------------
# Main polling loop
# ---------------------------------------------------------------------------


async def run_worker() -> None:
    """Main worker loop.  Runs forever as a separate OS process."""
    logger.info(
        "Ingestion worker started (poll interval: %ds)",
        settings.worker_poll_interval_seconds,
    )

    while True:
        try:
            async with AsyncSessionLocal() as db:
                job = await claim_next_job(db)

                if job is None:
                    # Queue is empty — wait before polling again.
                    await asyncio.sleep(settings.worker_poll_interval_seconds)
                    continue

                job_id = job.id
                document_id = job.document_id
                logger.info("Claimed job %s (document=%s)", job_id, document_id)

                try:
                    await process_job(job, db)
                except (PDFParseError, ValueError) as exc:
                    logger.error("Job %s failed (expected): %s", job_id, exc)
                    await _mark_job_failed(job_id, document_id, str(exc))
                except Exception as exc:
                    logger.exception("Job %s failed (unexpected): %s", job_id, exc)
                    await _mark_job_failed(job_id, document_id, str(exc))

        except Exception as exc:
            # Protect the loop against unexpected errors (e.g. DB connectivity).
            logger.exception("Unhandled error in worker loop: %s", exc)
            await asyncio.sleep(settings.worker_poll_interval_seconds)


if __name__ == "__main__":
    from app.core.logging_config import configure_logging

    configure_logging()
    asyncio.run(run_worker())

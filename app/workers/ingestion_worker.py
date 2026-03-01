"""
Ingestion worker — standalone async process (Process 2).

Polls the ingestion_jobs table and processes queued jobs.
Implemented in Phase 2.

Run with:
    python -m app.workers.ingestion_worker
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def main() -> None:
    logger.info("Ingestion worker starting — Phase 2 implementation pending")
    # Phase 2: claim_next_job → process_job loop with FOR UPDATE SKIP LOCKED


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(main())

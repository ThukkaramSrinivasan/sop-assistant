import logging

from fastapi import FastAPI

from app.api.v1 import ingest, query

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="SOP Assistant API",
    version="1.0.0",
    description="Multi-tenant AI backend for SOP (Standard Operating Procedure) analysis.",
)

app.include_router(ingest.router, prefix="/sop", tags=["ingest"])
app.include_router(query.router, prefix="/sop", tags=["query"])


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    """Liveness probe — returns 200 when the API process is running."""
    return {"status": "ok"}

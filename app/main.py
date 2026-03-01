import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse

from app.api.v1 import ingest, query
from app.core.logging_config import configure_logging

configure_logging()

logger = logging.getLogger(__name__)

app = FastAPI(
    title="SOP Assistant API",
    version="1.0.0",
    description="Multi-tenant AI backend for SOP (Standard Operating Procedure) analysis.",
)

app.include_router(ingest.router, prefix="/api/v1/sop", tags=["ingest"])
app.include_router(query.router, prefix="/api/v1/sop", tags=["query"])


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch all unhandled exceptions, log them internally, return a generic 500.

    HTTPException instances are re-raised so FastAPI's built-in handler deals
    with them — they carry intentional status codes and client-safe messages.
    All other exceptions are logged with full traceback (server-side only) and
    the client receives a generic message with no internal details.
    """
    if isinstance(exc, HTTPException):
        raise exc

    logger.exception(
        "Unhandled exception on %s %s", request.method, request.url.path
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred."},
    )


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    """Liveness probe — returns 200 when the API process is running."""
    return {"status": "ok"}

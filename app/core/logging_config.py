"""Structured JSON logging configuration.

Provides:
  customer_id_ctx   — ContextVar set by get_current_customer_id() on every
                      authenticated request; read by JsonFormatter so every
                      log line emitted during that request carries customer_id.
  configure_logging — call once at process startup to install the JSON handler.

Every log record produced anywhere in the application automatically inherits the
customer_id from the current async task's context — no changes to individual
logger call sites are required.
"""

import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone

# Default value "-" appears in log lines that have no active request context
# (e.g. startup, worker loops, unauthenticated routes like /health).
customer_id_ctx: ContextVar[str] = ContextVar("customer_id_ctx", default="-")


class JsonFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object.

    Fields:
      timestamp   — ISO-8601 UTC
      level       — DEBUG / INFO / WARNING / ERROR / CRITICAL
      logger      — dotted module name (e.g. app.api.v1.ingest)
      message     — formatted log message
      customer_id — from customer_id_ctx; "-" when not in a request context
      exception   — formatted traceback (only present when exc_info is set)
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "customer_id": customer_id_ctx.get(),
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


def configure_logging(level: int = logging.INFO) -> None:
    """Install the JSON formatter on the root logger.

    Call once at process startup (both API server and worker).
    Clears any handlers that basicConfig or uvicorn may have already installed
    so there is exactly one handler emitting structured JSON to stdout.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

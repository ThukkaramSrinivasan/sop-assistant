# Run tests with: pytest tests/ -v
#
# All tests use FastAPI's dependency_overrides to avoid live DB, OpenAI, or
# Anthropic calls.  The db_mock fixture replaces get_db with an in-memory
# MagicMock; the client fixture also bypasses get_current_customer_id so tests
# do not need valid JWTs.

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Environment variables — must be set before any app module is imported so
# that pydantic-settings picks them up when Settings() is instantiated.
# ---------------------------------------------------------------------------
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("EMBEDDING_MODEL", "text-embedding-3-small")
os.environ.setdefault("LLM_MODEL", "claude-sonnet-4-20250514")

from app.core.database import get_db  # noqa: E402
from app.core.security import get_current_customer_id  # noqa: E402
from app.main import app  # noqa: E402

# ---------------------------------------------------------------------------
# Shared test identifiers
# ---------------------------------------------------------------------------

TEST_CUSTOMER_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TEST_USER_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_mock():
    """In-memory DB session mock.  configure .execute.return_value per test."""
    mock = MagicMock()
    mock.execute = AsyncMock()
    mock.commit = AsyncMock()
    mock.refresh = AsyncMock()
    mock.add = MagicMock()
    return mock


@pytest.fixture()
def client(db_mock):
    """Authenticated test client.

    Overrides:
    - get_db            → yields db_mock (no live DB)
    - get_current_customer_id → returns TEST_CUSTOMER_ID (no JWT needed)
    """
    async def _override_db():
        yield db_mock

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_customer_id] = lambda: TEST_CUSTOMER_ID

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture()
def no_auth_client(db_mock):
    """Unauthenticated test client.

    Overrides get_db only — get_current_customer_id uses the real HTTPBearer
    dependency so requests without an Authorization header receive 403.
    """
    async def _override_db():
        yield db_mock

    app.dependency_overrides[get_db] = _override_db

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()

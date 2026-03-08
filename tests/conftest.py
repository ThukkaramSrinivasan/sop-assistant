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
from app.core.security import get_current_customer_id, get_current_user  # noqa: E402
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
    """In-memory DB session mock.  configure .execute.return_value per test.

    Python 3.13 changed AsyncMock so that its default return_value is also an
    AsyncMock rather than a MagicMock.  Accessing .scalars() on an AsyncMock
    yields another AsyncMock, and calling it returns a coroutine — so the chain
    result.scalars().first() raises AttributeError.  We fix this by explicitly
    setting a plain MagicMock as execute's return_value so all synchronous
    attribute access (.scalars, .scalar, .all, .first, .mappings) works correctly.

    Tests that need specific return values override db_mock.execute.return_value
    using _stub_execute_first (or similar helpers) within the test body.
    """
    mock = MagicMock()
    _result = MagicMock()
    _result.scalars.return_value.first.return_value = None
    _result.scalars.return_value.all.return_value = []
    _result.scalar.return_value = 0
    _result.all.return_value = []
    mock.execute = AsyncMock(return_value=_result)
    mock.commit = AsyncMock()
    mock.refresh = AsyncMock()
    mock.add = MagicMock()
    return mock


@pytest.fixture()
def client(db_mock):
    """Authenticated test client.

    Overrides:
    - get_db                  → yields db_mock (no live DB)
    - get_current_customer_id → returns TEST_CUSTOMER_ID (no JWT needed)
    - get_current_user        → returns a mock user with id + customer_id
    """
    mock_user = MagicMock()
    mock_user.id = TEST_USER_ID
    mock_user.customer_id = TEST_CUSTOMER_ID

    async def _override_db():
        yield db_mock

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_customer_id] = lambda: TEST_CUSTOMER_ID
    app.dependency_overrides[get_current_user] = lambda: mock_user

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

import logging
from datetime import datetime, timedelta
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging_config import customer_id_ctx

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer()

_ACCESS_TOKEN_EXPIRE_HOURS = 24


# ---------------------------------------------------------------------------
# Token creation
# ---------------------------------------------------------------------------


def create_access_token(user_id: UUID, customer_id: UUID) -> str:
    """Issue a signed JWT containing both user_id and customer_id."""
    expire = datetime.utcnow() + timedelta(hours=_ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {
        "user_id": str(user_id),
        "customer_id": str(customer_id),
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


# ---------------------------------------------------------------------------
# Token decoding (shared by both auth dependencies)
# ---------------------------------------------------------------------------


def _decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises 401 on any failure."""
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError:
        # Do not log the raw exception — it may contain token material.
        logger.warning("JWT decode failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ---------------------------------------------------------------------------
# Dependency: customer_id only (stateless — no DB round-trip)
# ---------------------------------------------------------------------------


async def get_current_customer_id(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> UUID:
    """FastAPI dependency — extracts customer_id from JWT.

    All tokens must contain both user_id and customer_id — issued exclusively
    by POST /api/v1/auth/login after bcrypt password verification.

    customer_id is NEVER accepted from the request body or query params.
    """
    payload = _decode_token(credentials.credentials)

    customer_id_str: str | None = payload.get("customer_id")
    if not customer_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing required customer_id claim",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        customer_id = UUID(customer_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="customer_id claim is not a valid UUID",
            headers={"WWW-Authenticate": "Bearer"},
        )

    customer_id_ctx.set(str(customer_id))
    return customer_id


# ---------------------------------------------------------------------------
# Dependency: full User record (DB round-trip — confirms user is still active)
# Requires a token issued by the login endpoint (must contain user_id)
# ---------------------------------------------------------------------------


def _get_db_dep():
    """Return the get_db dependency, imported lazily to keep this module
    importable before the database engine is initialised."""
    from app.core.database import get_db

    return get_db


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: AsyncSession = Depends(_get_db_dep()),
):
    """FastAPI dependency — returns the authenticated User DB record.

    Queries the DB to confirm the user still exists and is active.
    Use on endpoints that need full user identity beyond just customer_id.
    """
    from app.models.user import User

    payload = _decode_token(credentials.credentials)

    user_id_str: str | None = payload.get("user_id")
    customer_id_str: str | None = payload.get("customer_id")

    _invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not user_id_str or not customer_id_str:
        raise _invalid

    try:
        user_id = UUID(user_id_str)
        customer_id = UUID(customer_id_str)
    except ValueError:
        raise _invalid

    result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.customer_id == customer_id,
            User.is_active.is_(True),
        )
    )
    user = result.scalars().first()
    if user is None:
        raise _invalid

    customer_id_ctx.set(str(customer_id))
    return user

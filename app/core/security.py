import logging
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.config import settings
from app.core.logging_config import customer_id_ctx

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer()


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


async def get_current_customer_id(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> UUID:
    """
    FastAPI dependency.

    Extracts and returns the customer_id UUID from the JWT.
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

    # Inject into the logging context so every log line in this request
    # automatically includes customer_id without changing each call site.
    customer_id_ctx.set(str(customer_id))
    return customer_id

"""Auth endpoints.

POST /api/v1/auth/login — exchange email + password for a signed JWT.

Security rules enforced here:
  - Never reveal whether the email or the password was wrong — always the same
    generic 401 message (prevents user enumeration attacks).
  - hashed_password is never included in any response.
"""

import logging

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import create_access_token
from app.models.user import User
from app.schemas.auth import LoginRequest, LoginResponse

logger = logging.getLogger(__name__)

router = APIRouter()

_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Exchange email + password for a JWT",
)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """Authenticate a user and return a signed JWT.

    The same generic 401 is returned whether the email does not exist,
    the password is wrong, or the account is inactive — this prevents an
    attacker from enumerating valid email addresses.
    """
    result = await db.execute(
        select(User).where(User.email == body.email)
    )
    user = result.scalars().first()

    # Deliberate: do not distinguish "user not found" from "wrong password".
    if user is None or not user.is_active:
        raise _INVALID_CREDENTIALS

    if not bcrypt.checkpw(body.password.encode(), user.hashed_password.encode()):
        raise _INVALID_CREDENTIALS

    token = create_access_token(user_id=user.id, customer_id=user.customer_id)

    logger.info("User logged in: user=%s customer=%s", user.id, user.customer_id)

    return LoginResponse(
        access_token=token,
        user_id=user.id,
        customer_id=user.customer_id,
        email=user.email,
        full_name=user.full_name,
    )

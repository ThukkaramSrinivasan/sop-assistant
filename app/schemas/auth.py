from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    """Returned by POST /api/v1/auth/login."""

    access_token: str
    token_type: str = "bearer"
    user_id: UUID
    customer_id: UUID
    email: str
    full_name: Optional[str] = None
    # hashed_password is never included — only the DB model carries it

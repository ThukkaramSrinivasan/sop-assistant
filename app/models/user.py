from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Index
from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_customer_id", "customer_id"),
        Index("ix_users_email", "email"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    customer_id: UUID = Field(nullable=False, foreign_key="customers.id")
    email: str = Field(max_length=255, nullable=False)
    full_name: Optional[str] = Field(default=None, max_length=255)
    # bcrypt hash — never returned in any API response
    hashed_password: str = Field(max_length=255, nullable=False)
    is_active: bool = Field(default=True, nullable=False)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)

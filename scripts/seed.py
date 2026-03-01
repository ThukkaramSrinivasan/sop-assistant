#!/usr/bin/env python3
"""Seed the database with test customers and users.

Creates:
  Customer "Apollo Hospitals"  → alice@apollo.com / password123
  Customer "Legal Corp"        → bob@legalcorp.com / password123

Idempotent — safe to run multiple times; skips records that already exist.

Usage (from the project root):
    python scripts/seed.py
"""

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import bcrypt
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.customer import Customer
from app.models.user import User


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

SEED_DATA = [
    {
        "customer_name": "Apollo Hospitals",
        "email": "alice@apollo.com",
        "full_name": "Alice Apollo",
        "password": "password123",
    },
    {
        "customer_name": "Legal Corp",
        "email": "bob@legalcorp.com",
        "full_name": "Bob Legal",
        "password": "password123",
    },
]


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        for entry in SEED_DATA:
            # --- Customer ---------------------------------------------------
            result = await db.execute(
                select(Customer).where(Customer.name == entry["customer_name"])
            )
            customer = result.scalars().first()
            if customer is None:
                customer = Customer(name=entry["customer_name"])
                db.add(customer)
                await db.flush()  # populate customer.id before using it below

            # --- User -------------------------------------------------------
            result = await db.execute(
                select(User).where(User.email == entry["email"])
            )
            user = result.scalars().first()
            if user is None:
                user = User(
                    customer_id=customer.id,
                    email=entry["email"],
                    full_name=entry["full_name"],
                    hashed_password=_hash_password(entry["password"]),
                )
                db.add(user)
                await db.flush()

            print(
                f"{entry['customer_name']:<20} "
                f"customer_id={customer.id}  "
                f"user_id={user.id}  "
                f"email={entry['email']}"
            )

        await db.commit()


if __name__ == "__main__":
    asyncio.run(seed())

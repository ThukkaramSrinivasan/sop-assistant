#!/usr/bin/env python3
"""Generate signed JWTs for the two seed users for manual API testing.

Prerequisites:
    docker-compose up -d
    alembic upgrade head
    python scripts/seed.py

Connects to the database, looks up alice@apollo.com and bob@legalcorp.com,
and prints a ready-to-use Bearer token for each.  If neither user is found,
run the seed script first — this script never generates tokens with fake IDs.

Usage (from the project root):
    python scripts/generate_test_token.py
"""

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.customer import Customer
from app.models.user import User

_SEED_EMAILS = ["alice@apollo.com", "bob@legalcorp.com"]


async def _generate_tokens() -> None:
    found_any = False

    async with AsyncSessionLocal() as db:
        for email in _SEED_EMAILS:
            user_result = await db.execute(select(User).where(User.email == email))
            user = user_result.scalars().first()

            if user is None:
                print(f"  User not found: {email}  (run: python scripts/seed.py)")
                continue

            customer_result = await db.execute(
                select(Customer).where(Customer.id == user.customer_id)
            )
            customer = customer_result.scalars().first()
            customer_name = customer.name if customer else str(user.customer_id)

            token = create_access_token(user_id=user.id, customer_id=user.customer_id)

            print(f"Token for {email} ({customer_name}):")
            print(f"  Bearer {token}")
            print()
            found_any = True

    if not found_any:
        print("No seed users found in the database.")
        print("Run the seed script first:")
        print("    python scripts/seed.py")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(_generate_tokens())

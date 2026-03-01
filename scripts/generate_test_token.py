#!/usr/bin/env python3
"""Generate a signed JWT for manual API testing.

Reads JWT_SECRET and JWT_ALGORITHM from the project .env file and prints
a bearer token together with the embedded customer_id.

Usage (from the project root):
    python scripts/generate_test_token.py
"""

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so that app.* imports work even when
# the script is executed directly (not via `python -m`).
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from uuid import UUID

from jose import jwt

from app.core.config import settings

# Fixed customer_id used across all manual test requests.
# Copy this value when seeding the customers table or constructing curl calls.
TEST_CUSTOMER_ID: UUID = UUID("00000000-0000-0000-0000-000000000001")

payload = {"customer_id": str(TEST_CUSTOMER_ID)}

token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

print(f"customer_id : {TEST_CUSTOMER_ID}")
print(f"Bearer token: {token}")

"""Tests for the auth endpoint.

Covered:
  POST /api/v1/auth/login — exchange email + password for a JWT
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

_CUSTOMER_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_USER_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def _mock_user(*, is_active: bool = True) -> MagicMock:
    user = MagicMock()
    user.id = _USER_ID
    user.customer_id = _CUSTOMER_ID
    user.email = "alice@apollo.com"
    user.full_name = "Alice Apollo"
    user.is_active = is_active
    # Arbitrary string — bcrypt.checkpw is patched in tests that reach this call.
    user.hashed_password = "bcrypt-placeholder"
    return user


def _stub_user(db_mock, user):
    result = MagicMock()
    result.scalars.return_value.first.return_value = user
    db_mock.execute.return_value = result


class TestLogin:
    def test_valid_credentials_return_200(self, client, db_mock):
        _stub_user(db_mock, _mock_user())
        with patch("app.api.v1.auth.bcrypt.checkpw", return_value=True):
            resp = client.post(
                "/api/v1/auth/login",
                json={"email": "alice@apollo.com", "password": "password123"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert "user_id" in body
        assert "customer_id" in body

    def test_wrong_password_returns_401(self, client, db_mock):
        _stub_user(db_mock, _mock_user())
        with patch("app.api.v1.auth.bcrypt.checkpw", return_value=False):
            resp = client.post(
                "/api/v1/auth/login",
                json={"email": "alice@apollo.com", "password": "wrong-password"},
            )

        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid credentials"

    def test_unknown_email_returns_401(self, client, db_mock):
        # DB returns None — user does not exist.
        _stub_user(db_mock, None)
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "password123"},
        )

        assert resp.status_code == 401
        # Same message as wrong password — prevents user enumeration.
        assert resp.json()["detail"] == "Invalid credentials"

    def test_inactive_user_returns_401(self, client, db_mock):
        _stub_user(db_mock, _mock_user(is_active=False))
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "alice@apollo.com", "password": "password123"},
        )

        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid credentials"

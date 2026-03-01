"""Add users table.

Adds the users table which stores per-customer user accounts with bcrypt-hashed
passwords.  One customer has many users; email is unique across the whole table.

Revision ID: 002
Revises: 001
"""

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id              UUID         NOT NULL PRIMARY KEY,
            customer_id     UUID         NOT NULL REFERENCES customers(id),
            email           VARCHAR(255) NOT NULL UNIQUE,
            full_name       VARCHAR(255),
            hashed_password VARCHAR(255) NOT NULL,
            is_active       BOOLEAN      NOT NULL DEFAULT true,
            created_at      TIMESTAMP    NOT NULL DEFAULT NOW()
        )
    """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_customer_id ON users (customer_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_email ON users (email)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_email")
    op.execute("DROP INDEX IF EXISTS ix_users_customer_id")
    op.execute("DROP TABLE IF EXISTS users")

"""Add sources_relevant to ai_responses.

Records whether the LLM determined its answer was grounded in the provided
context (true) or was a refusal/out-of-scope response (false).

NULL for rows created before this migration — column is intentionally
nullable so existing audit records do not need backfilling.

Revision ID: 004
Revises: 003
"""

from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ai_responses ADD COLUMN IF NOT EXISTS sources_relevant BOOLEAN"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE ai_responses DROP COLUMN IF EXISTS sources_relevant"
    )

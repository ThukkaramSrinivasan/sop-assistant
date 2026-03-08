"""Add conversation fields to ai_responses.

Adds three nullable columns to ai_responses to support multi-turn
conversation context retention:

  conversation_id       UUID   — groups all turns of one conversation session
  turn_number           INT    — 1-based position of this turn within the session
  conversation_history  JSONB  — messages array sent to the LLM this turn
                                 (list of {role, content} objects)

NULL for rows created before this migration — column is intentionally
nullable so existing audit records do not need backfilling.

Also adds an index on conversation_id for efficient session-level queries
(e.g. retrieve all turns of a conversation).

Revision ID: 005
Revises: 004
"""

from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ai_responses ADD COLUMN IF NOT EXISTS conversation_id UUID"
    )
    op.execute(
        "ALTER TABLE ai_responses ADD COLUMN IF NOT EXISTS turn_number INTEGER"
    )
    op.execute(
        "ALTER TABLE ai_responses ADD COLUMN IF NOT EXISTS conversation_history JSONB"
    )
    op.create_index(
        "ix_ai_responses_conversation_id",
        "ai_responses",
        ["conversation_id"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_ai_responses_conversation_id", table_name="ai_responses")
    op.execute(
        "ALTER TABLE ai_responses DROP COLUMN IF EXISTS conversation_history"
    )
    op.execute(
        "ALTER TABLE ai_responses DROP COLUMN IF EXISTS turn_number"
    )
    op.execute(
        "ALTER TABLE ai_responses DROP COLUMN IF EXISTS conversation_id"
    )

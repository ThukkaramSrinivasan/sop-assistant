"""Add page_number to document_chunks.

Tracks which PDF page each chunk was extracted from so the UI can show
"Page N" citations instead of opaque chunk indices.

NULL for chunks ingested before this migration — the column is intentionally
nullable so existing data does not need backfilling.

Revision ID: 003
Revises: 002
"""

from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS page_number INTEGER"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE document_chunks DROP COLUMN IF EXISTS page_number"
    )

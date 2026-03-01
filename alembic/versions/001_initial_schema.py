"""Initial schema: pgvector extension, all tables, indexes, RLS policy.

Revision ID: 001
Revises:
Create Date: 2025-02-28

Tables created:
  customers         — tenant registry
  documents         — uploaded SOP PDFs (soft-delete, hash-dedup)
  document_chunks   — chunked text with pgvector embeddings (RLS-protected)
  ai_responses      — full audit trail of LLM responses (never deleted)
  ingestion_jobs    — Postgres-native job queue (FOR UPDATE SKIP LOCKED)

Notable:
  - pgvector extension enabled
  - HNSW index on document_chunks.embedding for fast cosine search
  - customer_id indexes on all tenant-scoped tables
  - RLS policy on document_chunks as defense-in-depth alongside app-level filtering

All table DDL uses raw SQL (CREATE TABLE IF NOT EXISTS) so that SQLAlchemy's
internal Enum type management cannot interfere. Enum types are created via DO
blocks that swallow duplicate_object errors, making the whole migration safe to
re-run after a partial failure.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Enable pgvector — must come before any vector column or index
    # ------------------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ------------------------------------------------------------------
    # 2. Enum types
    #
    # PostgreSQL has no CREATE TYPE IF NOT EXISTS, so we use a DO block
    # that catches the duplicate_object error and treats it as a no-op.
    # ------------------------------------------------------------------
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE documentstatus
                AS ENUM ('pending', 'processing', 'completed', 'failed');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE jobstatus
                AS ENUM ('queued', 'processing', 'completed', 'failed');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )

    # ------------------------------------------------------------------
    # 3. customers
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS customers (
            id          UUID         PRIMARY KEY,
            name        VARCHAR(255) NOT NULL,
            created_at  TIMESTAMP    NOT NULL DEFAULT NOW()
        )
        """
    )

    # ------------------------------------------------------------------
    # 4. documents
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id          UUID             PRIMARY KEY,
            customer_id UUID             NOT NULL,
            filename    VARCHAR(512)     NOT NULL,
            file_hash   VARCHAR(64)      NOT NULL,
            status      documentstatus   NOT NULL DEFAULT 'pending',
            version     INTEGER          NOT NULL DEFAULT 1,
            is_active   BOOLEAN          NOT NULL DEFAULT true,
            created_at  TIMESTAMP        NOT NULL DEFAULT NOW()
        )
        """
    )
    op.create_index(
        "ix_documents_customer_id", "documents", ["customer_id"], if_not_exists=True
    )

    # ------------------------------------------------------------------
    # 5. document_chunks
    #    embedding column uses pgvector vector(1536) — added separately
    #    so the table can be created without pgvector being involved in
    #    the CREATE TABLE statement itself.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS document_chunks (
            id              UUID         PRIMARY KEY,
            document_id     UUID         NOT NULL REFERENCES documents(id),
            customer_id     UUID         NOT NULL,
            chunk_index     INTEGER      NOT NULL,
            chunk_text      TEXT         NOT NULL,
            token_count     INTEGER      NOT NULL,
            embedding_model VARCHAR(100),
            is_active       BOOLEAN      NOT NULL DEFAULT true,
            embedded_at     TIMESTAMP
        )
        """
    )

    # Add vector column separately — IF NOT EXISTS keeps this idempotent
    op.execute(
        "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS embedding vector(1536)"
    )

    op.create_index(
        "ix_document_chunks_customer_id",
        "document_chunks",
        ["customer_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_document_chunks_document_id",
        "document_chunks",
        ["document_id"],
        if_not_exists=True,
    )

    # HNSW index — approximate nearest-neighbour with cosine distance.
    # Chosen over IVFFlat: no training step required, better accuracy at
    # low row counts, and simpler operations.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw
        ON document_chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )

    # ------------------------------------------------------------------
    # 6. ai_responses — immutable audit trail, never deleted
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_responses (
            id                   UUID     PRIMARY KEY,
            customer_id          UUID     NOT NULL,
            query_text           TEXT     NOT NULL,
            prompt_sent          TEXT     NOT NULL,
            retrieved_chunk_ids  UUID[]   NOT NULL,
            model_name           VARCHAR(100) NOT NULL,
            model_temperature    FLOAT    NOT NULL,
            response_text        TEXT     NOT NULL,
            confidence_score     FLOAT,
            latency_ms           INTEGER  NOT NULL,
            created_at           TIMESTAMP NOT NULL DEFAULT NOW(),
            created_by           UUID     NOT NULL
        )
        """
    )
    op.create_index(
        "ix_ai_responses_customer_id",
        "ai_responses",
        ["customer_id"],
        if_not_exists=True,
    )

    # ------------------------------------------------------------------
    # 7. ingestion_jobs — Postgres-native job queue
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ingestion_jobs (
            id            UUID        PRIMARY KEY,
            document_id   UUID        NOT NULL REFERENCES documents(id),
            customer_id   UUID        NOT NULL,
            status        jobstatus   NOT NULL DEFAULT 'queued',
            error_message TEXT,
            enqueued_at   TIMESTAMP   NOT NULL DEFAULT NOW(),
            started_at    TIMESTAMP,
            completed_at  TIMESTAMP
        )
        """
    )
    op.create_index(
        "ix_ingestion_jobs_customer_id",
        "ingestion_jobs",
        ["customer_id"],
        if_not_exists=True,
    )
    # Composite index optimises the worker poll query:
    # WHERE status = 'queued' ORDER BY enqueued_at ASC FOR UPDATE SKIP LOCKED
    op.create_index(
        "ix_ingestion_jobs_status_enqueued_at",
        "ingestion_jobs",
        ["status", "enqueued_at"],
        if_not_exists=True,
    )

    # ------------------------------------------------------------------
    # 8. Row-Level Security on document_chunks (defense in depth)
    #
    # The application enforces tenant isolation via WHERE customer_id = ?
    # on every query. RLS provides a second, independent enforcement layer
    # so that an application bug cannot leak cross-tenant data.
    #
    # Production setup required:
    #   1. Create a limited-privilege role (no BYPASSRLS) for the API.
    #   2. Before each query, SET LOCAL app.current_customer_id = '<uuid>'.
    #   3. The worker connects as a superuser (bypasses RLS automatically).
    #
    # Development: the postgres superuser bypasses RLS, so this is a
    # no-op locally but enforced in production.
    # ------------------------------------------------------------------
    op.execute("ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY")

    # PostgreSQL has no CREATE POLICY IF NOT EXISTS — drop first instead.
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON document_chunks")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON document_chunks
        AS RESTRICTIVE
        FOR ALL
        USING (
            customer_id = NULLIF(
                current_setting('app.current_customer_id', true), ''
            )::uuid
        )
        """
    )
    op.execute(
        "COMMENT ON POLICY tenant_isolation ON document_chunks IS "
        "'Defense-in-depth: SET LOCAL app.current_customer_id before each query. "
        "Superusers (worker, migrations) bypass automatically.'"
    )


def downgrade() -> None:
    # RLS
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON document_chunks")
    op.execute("ALTER TABLE document_chunks DISABLE ROW LEVEL SECURITY")

    # Tables (reverse FK dependency order)
    op.drop_table("ingestion_jobs")
    op.drop_table("ai_responses")
    op.drop_table("document_chunks")
    op.drop_table("documents")
    op.drop_table("customers")

    # Enum types
    op.execute("DROP TYPE IF EXISTS jobstatus")
    op.execute("DROP TYPE IF EXISTS documentstatus")

    # Note: intentionally NOT dropping the vector extension — it may be
    # used by other databases in the same Postgres cluster.

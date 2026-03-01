# SOP Assistant — Project Memory

## Status
Phase 1 complete. Phase 2 (ingestion pipeline) is next.

## Key Architecture Notes
- Two processes: FastAPI API server (Process 1) + ingestion worker (Process 2)
- No Redis — Postgres job queue with FOR UPDATE SKIP LOCKED
- pgvector in same Postgres instance (pgvector/pgvector:pg15 Docker image)
- customer_id always from JWT, never from request body

## Critical Patterns
- DB models in `app/models/` (SQLModel, table=True) — NEVER returned from API endpoints
- API schemas in `app/schemas/` (Pydantic BaseModel) — the public contract
- AsyncSession everywhere; no sync SQLAlchemy
- temperature=0 for all LLM calls; full prompt stored verbatim for audit

## Enum Types (PostgreSQL)
- `documentstatus`: pending, processing, completed, failed
- `jobstatus`: queued, processing, completed, failed
- Both use `create_type=False` in SQLModel (types created explicitly in migration)

## Vector Column
- `document_chunks.embedding` is `vector(1536)` (text-embedding-3-small output)
- Added via `op.execute("ALTER TABLE document_chunks ADD COLUMN embedding vector(1536)")` in migration
- SQLModel model uses `pgvector.sqlalchemy.Vector` via `sa_column=Column(Vector(1536))`
- HNSW index: `USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)`

## Alembic
- Uses asyncio mode (create_async_engine + conn.run_sync) — asyncpg, no psycopg2 needed at runtime
- env.py imports all models via `app.models.*` for autogenerate discovery
- Initial migration: `alembic/versions/001_initial_schema.py` (revision="001")

## RLS Policy
- Enabled on `document_chunks` as defense-in-depth
- RESTRICTIVE policy using `current_setting('app.current_customer_id', true)`
- Superusers (worker, migrations) bypass automatically
- App role must `SET LOCAL app.current_customer_id = '<uuid>'` before queries

## Local Dev Commands
```bash
docker-compose up -d          # start postgres
alembic upgrade head          # run migrations
uvicorn app.main:app --reload --port 8000  # API server
python -m app.workers.ingestion_worker     # worker
```

## Phase 2 Will Add
- app/services/ingestion/parser.py (pdfplumber)
- app/services/ingestion/chunker.py (tiktoken, 512 tokens, 50 overlap)
- app/services/ingestion/embedder.py (OpenAI batched calls, file_hash dedup)
- app/workers/ingestion_worker.py (FOR UPDATE SKIP LOCKED polling loop)
- app/api/v1/ingest.py endpoints (POST /sop/ingest, GET /sop/ingest/jobs/{id})

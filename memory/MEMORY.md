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

## Phase 2 Complete
- parser.py: PDFParseError + extract_text_from_pdf (pdfplumber, handles empty/corrupt)
- chunker.py: ChunkData dataclass + chunk_text with paragraph-aware algorithm
  - Splits on \n\n first, greedily accumulates, flushes at chunk_size with overlap tail carry-over
  - Sub-splits oversized paragraphs via push() helper
  - Overlap check: use enc.decode(enc.encode(tail)[-N:]) then find in next chunk TEXT (not re-encoded tokens — BPE is context-sensitive at boundaries)
- embedder.py: embed_chunks (batched ≤100, sorts by index), should_skip_ingestion (checks completed docs by file_hash+customer_id), upsert_chunks (soft-deletes stale chunks first)
- ingestion_worker.py: claim_next_job (FOR UPDATE SKIP LOCKED), process_job (dedup → process → complete), _mark_job_failed (fresh session for safety), run_worker loop
- ingest.py: POST /sop/ingest (202, PDF magic check, 10MB limit, saves to uploads/{customer_id}/{document_id}.pdf), GET /sop/ingest/jobs/{job_id}
- UPLOAD_DIR = Path("uploads") defined in BOTH ingest.py and ingestion_worker.py — must stay in sync

## Phase 3 Will Add
- app/services/rag/retriever.py, prompt.py, generator.py
- app/api/v1/query.py endpoints (POST /sop/query, GET /sop/responses/{id})

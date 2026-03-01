# PLAN.md — Engineering Plan

## Goal
Build a multi-tenant AI backend service for SOP analysis.
Emphasis: architecture, data modeling, AI workflows, and trade-offs.
This is an assignment submission — clear design matters more than a fully running product.

## Phases Overview

Note: Phases 1-5 were planned upfront. Phase 6 (B2B Auth + Frontend UI) was added mid-implementation based on requirements that emerged during development — specifically the need for proper multi-user B2B login and a demo-ready interface.

```
Phase 1 → Project scaffold + DB schema + migrations
Phase 2 → Ingestion pipeline (PDF → chunks → embeddings → job queue)
Phase 3 → RAG query pipeline (search → prompt → LLM → audit record)
Phase 4 → Cross-cutting concerns (error handling, validation, logging)
Phase 5 → Docs and submission artifacts (README, AI_USAGE, diagrams)
```

---

## Phase 1: Foundation
**Goal**: Runnable project skeleton with correct schema. Data model is solid before any feature work.

### Tasks
- [ ] Initialize repo, `.gitignore`, `requirements.txt`
- [ ] `docker-compose.yml` — single postgres (pgvector) container, no Redis
- [ ] `app/core/config.py` — pydantic-settings, all values from `.env`
- [ ] `app/core/database.py` — async SQLAlchemy engine, `AsyncSession`, `get_db` dependency
- [ ] `app/core/security.py` — JWT decode, `get_current_customer_id()` FastAPI dependency
- [ ] SQLModel DB models (`app/models/`):
  - `customers` — id, name, created_at
  - `documents` — id, customer_id, filename, file_hash (SHA-256), status, version, is_active, created_at
  - `document_chunks` — id, document_id, customer_id, chunk_index, chunk_text, token_count, embedding vector(1536), embedding_model, is_active, embedded_at
  - `ai_responses` — id, customer_id, query_text, prompt_sent, retrieved_chunk_ids (UUID[]), model_name, model_temperature, response_text, confidence_score, latency_ms, created_at, created_by
  - `ingestion_jobs` — id, document_id, customer_id, status, error_message, enqueued_at, started_at, completed_at
- [ ] Alembic setup + initial migration
  - Enable pgvector: `CREATE EXTENSION IF NOT EXISTS vector`
  - Add `vector(1536)` column on `document_chunks`
  - Add HNSW index: `CREATE INDEX ON document_chunks USING hnsw (embedding vector_cosine_ops)`
  - Add indexes on `customer_id` for all tenant-scoped tables
- [ ] Row-Level Security policy on `document_chunks` (defense in depth)
- [ ] FastAPI app skeleton with `GET /health` endpoint
- [ ] `.env.example` with all required vars

### Deliverable
`docker-compose up && alembic upgrade head` succeeds. Schema is correct with pgvector enabled.

---

## Phase 2: Ingestion Pipeline
**Goal**: Upload PDF → job queued → worker picks it up → chunks embedded and stored.

### Process Note
Ingestion spans both processes:
- **API process**: accepts upload, saves file, creates document record, enqueues job
- **Worker process**: does all the slow work (parse, chunk, embed, store)

### Tasks

**Parser** (`app/services/ingestion/parser.py`)
- [ ] `extract_text_from_pdf(filepath: str) -> str` using pdfplumber
- [ ] Handle corrupt/empty PDFs — raise a typed exception, don't crash worker

**Chunker** (`app/services/ingestion/chunker.py`)
- [ ] `chunk_text(text, chunk_size=512, overlap=50) -> list[ChunkData]`
- [ ] Use `tiktoken` for token counting (not character counting)
- [ ] Respect paragraph boundaries — split on `\n\n` first, then token-limit
- [ ] Each `ChunkData`: `chunk_index`, `chunk_text`, `token_count`

**Embedder** (`app/services/ingestion/embedder.py`)
- [ ] `embed_chunks(chunks: list[ChunkData]) -> list[list[float]]`
- [ ] Batch OpenAI calls — max 100 chunks per request
- [ ] `upsert_chunks(document_id, customer_id, chunks, embeddings, db)` — write to DB
- [ ] `should_skip_ingestion(file_hash, customer_id, db) -> bool` — check hash to avoid re-embedding

**Worker** (`app/workers/ingestion_worker.py`)
- [ ] Standalone async polling loop — runs as separate process
- [ ] `claim_next_job(db) -> IngestionJob | None` — uses `FOR UPDATE SKIP LOCKED`
- [ ] `process_job(job, db)` — orchestrates parse → chunk → embed → mark complete
- [ ] On failure: set status to `failed`, store `error_message`, do not crash loop
- [ ] Sleep `WORKER_POLL_INTERVAL_SECONDS` when queue is empty

**Ingest API** (`app/api/v1/ingest.py`)
- [ ] `POST /sop/ingest` — multipart PDF upload
  - Save file to local storage
  - Compute SHA-256 hash
  - Create `documents` record (status: `pending`)
  - Create `ingestion_jobs` record (status: `queued`)
  - Return `202 Accepted` with `{ job_id, document_id, status: "queued" }`
- [ ] `GET /sop/ingest/jobs/{job_id}` — return job status
  - customer_id from JWT must match job's customer_id
  - Return `{ job_id, status, document_id, error_message? }`

**API Schemas** (`app/schemas/ingest.py`)
- [ ] `IngestResponse` — job_id, document_id, status
- [ ] `JobStatusResponse` — job_id, status, document_id, error_message, completed_at

### Deliverable
Upload a PDF → poll job status → status becomes `completed` → chunks with embeddings exist in DB.

> **Note (post-implementation):** Versioning logic added after test_versioning.py revealed that
> version and is_active fields existed in the schema but were not populated correctly by ingest.py.
> Fixed by adding a filename lookup before document creation and soft-deleting old chunks after
> new embeddings are stored.

---

## Phase 3: RAG Query Pipeline
**Goal**: User asks a question → gets a cited, auditable AI response using only their own data.

### Tasks

**Retriever** (`app/services/rag/retriever.py`)
- [ ] `embed_query(query_text: str) -> list[float]`
  - Same model as ingestion — `text-embedding-3-small`
- [ ] `retrieve_chunks(query_embedding, customer_id, document_ids=None, top_k=5, db) -> list[RetrievedChunk]`
  - pgvector cosine similarity search
  - `customer_id` filter is mandatory — never omit
  - Optional `document_ids` filter for scoped queries
  - Returns: chunk_id, chunk_text, document_filename, chunk_index, similarity_score

**Prompt Builder** (`app/services/rag/prompt.py`)
- [ ] `build_prompt(query: str, chunks: list[RetrievedChunk]) -> str`
- [ ] Template structure:
  ```
  System:
  You are an AI assistant that analyzes Standard Operating Procedures (SOPs).
  Use ONLY the context provided below. Do not use any outside knowledge.
  If the answer is not in the context, explicitly say so.
  Always cite sources using [Source N] notation.

  Context:
  [Source 1 — {filename}, section {chunk_index}]
  {chunk_text}

  [Source 2 — ...]
  {chunk_text}

  User Query: {query}
  ```

**Generator** (`app/services/rag/generator.py`)
- [ ] `generate(query, customer_id, created_by, document_ids=None, db) -> QueryResponse`
  - Embed query
  - Retrieve top-k chunks (with customer_id filter)
  - Build prompt
  - Call Anthropic API: `temperature=0`, `model=claude-sonnet-4-20250514`
  - Measure latency
  - Store full `ai_responses` record — prompt_sent, retrieved_chunk_ids, model params
  - Map to `QueryResponse` schema — never return DB model directly

**Query API** (`app/api/v1/query.py`)
- [ ] `POST /sop/query`
  - Body: `{ query: str, document_ids?: list[UUID] }`
  - customer_id from JWT only
  - Returns `QueryResponse`
- [ ] `GET /sop/responses/{id}`
  - Full audit record including prompt_sent, retrieved_chunk_ids, model metadata
  - customer_id from JWT must match response's customer_id

**API Schemas** (`app/schemas/query.py`, `app/schemas/audit.py`)
- [ ] `QueryRequest` — query, document_ids (optional)
- [ ] `SourceCitation` — chunk_id, document_filename, chunk_index, relevance_score
- [ ] `QueryResponse` — response_id, answer, sources (list[SourceCitation]), model, generated_at
- [ ] `AuditResponse` — everything in QueryResponse + prompt_sent, retrieved_chunk_ids, latency_ms, model_temperature

### Target Response Shape
```json
{
  "response_id": "uuid",
  "answer": "Based on SOP-2021-ICU-Meds [Source 1], the correct protocol requires...",
  "sources": [
    {
      "chunk_id": "uuid",
      "document_filename": "SOP-2021-ICU-Meds.pdf",
      "chunk_index": 4,
      "relevance_score": 0.91
    }
  ],
  "model": "claude-sonnet-4-20250514",
  "generated_at": "2025-02-28T10:00:00Z"
}
```

### Audit Record Shape (GET /sop/responses/{id})
```json
{
  "response_id": "uuid",
  "answer": "...",
  "sources": [...],
  "model": "claude-sonnet-4-20250514",
  "generated_at": "2025-02-28T10:00:00Z",
  "audit": {
    "prompt_sent": "System: You are an AI assistant...[full prompt verbatim]",
    "retrieved_chunk_ids": ["uuid1", "uuid2", "uuid3"],
    "latency_ms": 1240,
    "model_temperature": 0
  }
}
```

### Deliverable
`POST /sop/query` returns a cited answer. `GET /sop/responses/{id}` exposes full audit trail.

---

## Phase 4: Cross-Cutting Concerns
**Goal**: Make the system robust — proper errors, validation, logging.

### Tasks
- [ ] Global exception handler — catch all unhandled exceptions, return generic 500, log internally
- [ ] Never expose raw DB errors or stack traces to clients
- [ ] Structured JSON logging with `customer_id` included in every log line
- [ ] Validate file type on upload (PDF only) and file size (max 10MB)
- [ ] API versioned under `/api/v1/`

---

## Phase 5: Docs and Submission Artifacts
**Goal**: All written deliverables the assignment requires.

### Tasks
- [ ] `README.md`
  - What the system does
  - Assumptions made
  - Design decisions with reasoning
  - Trade-offs table (see below)
  - How to run locally (step by step)
  - Mermaid ER diagram
  - Auditable AI response payload example
- [ ] `AI_USAGE.md`
  - Tools used and purpose
  - Representative prompts (paraphrased)
  - What was changed after reviewing AI output
  - At least one example of rejected AI output and why

---

## Trade-offs to Document in README

| Decision | Choice Made | Alternative | Reasoning |
|---|---|---|---|
| Vector DB | pgvector in Postgres | Pinecone, Weaviate | Simpler ops, tenant filter via SQL WHERE, no extra service |
| Job queue | Postgres table + `FOR UPDATE SKIP LOCKED` | Redis + ARQ, SQS | No extra infrastructure; sufficient for this scale |
| Ingestion | Async (separate worker process) | Sync HTTP | PDFs take 30-60s to process; can't block HTTP |
| Query | Sync HTTP | SSE streaming | 1k/day volume; sync is simpler and sufficient |
| Chunking | 512 tokens, 50 overlap | Document-level | Chunk-level gives much better retrieval precision |
| LLM temperature | 0 | >0 | Determinism required for auditability in regulated domains |
| Tenant isolation | customer_id filter + RLS | Separate DB per tenant | Cost-effective; enforced at two independent layers |
| Models vs Schemas | Separate DB models and API schemas | Unified (SQLModel dual-use) | Clean boundary — DB internals never leak to API consumers |

---

## Claude Code Prompts (Use These in Order)

**Phase 1:**
> "Read CLAUDE.md. Scaffold Phase 1 from docs/PLAN.md: docker-compose with postgres+pgvector (no Redis), async SQLAlchemy setup with AsyncSession, all 5 SQLModel DB models, Alembic initial migration with pgvector extension + HNSW index + customer_id indexes, RLS policy on document_chunks, and a FastAPI /health endpoint."

**Phase 2:**
> "Read CLAUDE.md and Phase 2 in docs/PLAN.md. Implement the ingestion pipeline: parser.py with pdfplumber, chunker.py using tiktoken with paragraph-aware splitting, embedder.py with batched OpenAI calls and file_hash dedup check. Then implement the standalone worker process in ingestion_worker.py using FOR UPDATE SKIP LOCKED. Finally implement the ingest API endpoints with separate Pydantic response schemas."

**Phase 3:**
> "Read CLAUDE.md and Phase 3 in docs/PLAN.md. Implement the RAG pipeline: retriever.py with pgvector cosine search and mandatory customer_id filter, prompt.py using the template in the plan, generator.py that stores the full audit record. Implement the query API endpoints. Use separate Pydantic schemas — never return DB models directly."

**Phase 4:**
> "Read CLAUDE.md and Phase 4 in docs/PLAN.md. Add: global exception handler that never leaks DB errors, structured JSON logging with customer_id in every line, file type and size validation on upload."

**Phase 5:**
> "Read CLAUDE.md and PLAN.md. Generate README.md with assumptions, design decisions, the trade-offs table from the plan, a Mermaid ER diagram, and an example audit response payload. Also generate AI_USAGE.md."
## Phase 6: B2B Auth + Frontend UI

### Tasks
- [ ] Alembic migration for users table
- [ ] passlib[bcrypt] added to requirements.txt
- [ ] scripts/seed.py — creates 2 customers + 2 users, idempotent, prints ids
- [ ] app/core/security.py — JWT updated to include user_id, get_current_user() added
- [ ] POST /api/v1/auth/login
- [ ] GET /api/v1/sop/documents
- [ ] CORS middleware in app/main.py for http://localhost:5173
- [ ] /frontend scaffolded with Vite + React + Tailwind
- [ ] Login page
- [ ] Documents page with upload + status badges
- [ ] Chat page with message history and source chips
- [ ] Shared Navbar with dark/light toggle and logout
- [ ] frontend/.env and frontend/.env.example

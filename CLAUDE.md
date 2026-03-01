# CLAUDE.md — AI Platform Backend (Unifize Assignment)

## What This Project Is
A multi-tenant AI-backed backend service for SOP (Standard Operating Procedure) analysis.
Users upload PDFs, the system chunks and embeds them, and provides RAG-powered AI responses
with full auditability. Built for regulated industries (healthcare, legal) where hallucination
and data leakage are unacceptable.

## Tech Stack
- **Language**: Python 3.11+
- **Framework**: FastAPI
- **Primary DB**: PostgreSQL 15 with pgvector extension
- **Vector Search**: pgvector (same Postgres instance — no separate vector DB needed)
- **Job Queue**: Postgres `ingestion_jobs` table with `FOR UPDATE SKIP LOCKED` (no Redis)
- **Embeddings**: OpenAI `text-embedding-3-small`
- **LLM**: Anthropic Claude via API (`claude-sonnet-4-20250514`)
- **PDF Parsing**: pdfplumber
- **ORM**: SQLAlchemy 2.0 async + SQLModel for DB models
- **API Schemas**: Separate Pydantic `BaseModel` classes (never reuse DB models as API responses)
- **Migrations**: Alembic
- **Auth**: JWT (customer_id extracted server-side only, never from request body)
- **Containerization**: Docker + docker-compose

---

## Two Separate Processes
This project runs as **two independent processes**. Same codebase, same DB, never merged.

```
Process 1 — API Server (FastAPI)
  - Handles HTTP requests
  - Fast, short-lived, concurrent
  - Writes jobs to ingestion_jobs table
  - Serves RAG query responses

Process 2 — Ingestion Worker (async polling loop)
  - Polls ingestion_jobs table for queued jobs
  - Does slow work: PDF parse → chunk → embed → store
  - Completely independent — can crash without affecting API
  - No HTTP server, no ports exposed
```

Start locally:
```bash
# Terminal 1 — API server
uvicorn app.main:app --reload --port 8000

# Terminal 2 — Worker (separate process)
python -m app.workers.ingestion_worker
```

In Docker, two separate containers from the same image, different startup commands.

---

## Project Structure
```
/
├── CLAUDE.md
├── docs/
│   └── PLAN.md
├── alembic/                         # DB migrations
├── app/
│   ├── main.py                      # FastAPI app entry point
│   ├── core/
│   │   ├── config.py                # Settings via pydantic-settings
│   │   ├── database.py              # Async SQLAlchemy engine + AsyncSession
│   │   └── security.py             # JWT decode, get_current_customer_id dependency
│   ├── models/                      # SQLModel DB models (storage layer only)
│   │   ├── customer.py
│   │   ├── document.py
│   │   ├── chunk.py
│   │   ├── ai_response.py
│   │   └── ingestion_job.py
│   ├── schemas/                     # Pydantic API schemas (API contract layer)
│   │   ├── ingest.py                # IngestResponse, JobStatusResponse
│   │   ├── query.py                 # QueryRequest, QueryResponse, SourceCitation
│   │   └── audit.py                 # AuditResponse
│   ├── api/
│   │   └── v1/
│   │       ├── ingest.py            # POST /sop/ingest, GET /sop/ingest/jobs/{id}
│   │       └── query.py             # POST /sop/query, GET /sop/responses/{id}
│   ├── services/
│   │   ├── ingestion/
│   │   │   ├── parser.py            # PDF text extraction (pdfplumber)
│   │   │   ├── chunker.py           # Chunking with tiktoken
│   │   │   └── embedder.py          # OpenAI embedding calls + pgvector upsert
│   │   └── rag/
│   │       ├── retriever.py         # pgvector search with mandatory customer_id filter
│   │       ├── prompt.py            # Prompt construction from retrieved chunks
│   │       └── generator.py         # Anthropic API call + audit record storage
│   └── workers/
│       └── ingestion_worker.py      # Standalone async worker loop (Process 2)
├── tests/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
├── README.md
└── AI_USAGE.md
```

---

## Models vs Schemas — Strict Separation (Important)

**DB Models** (`app/models/`) — SQLModel classes with `table=True`.
Internal representation of stored data. May contain fields that must never be exposed via API.

**API Schemas** (`app/schemas/`) — Plain Pydantic `BaseModel` classes.
The deliberate contract with API consumers. Only expose what the client needs.

```python
# DB Model — internal, has fields that must never leave the server
class DocumentChunk(SQLModel, table=True):
    id: UUID
    customer_id: UUID
    file_hash: str        # internal — skip re-embedding, never expose
    is_active: bool       # internal — soft delete flag, never expose
    embedding_model: str  # internal, never expose
    chunk_text: str

# API Schema — separate deliberate contract for the client
class SourceCitation(BaseModel):
    chunk_id: UUID
    document_filename: str
    chunk_index: int
    relevance_score: float
    # no internal fields here
```

**Rule**: Never return a DB model instance directly from an API endpoint.
Always explicitly map to an API schema.

---

## Non-Negotiable Rules

### Tenant Isolation
- `customer_id` is ALWAYS extracted from JWT. Never from request body or query params.
- Every DB query MUST include a `customer_id` filter. No exceptions.
- Every pgvector search MUST include `customer_id` as a filter. No exceptions.
- Never return raw DB errors to the client — they may leak schema or tenant info.

### AI / LLM
- Always use `temperature=0` for deterministic, auditable responses.
- Always store the full constructed prompt verbatim in `ai_responses.prompt_sent`.
- Always store the exact chunk IDs used as context in `ai_responses.retrieved_chunk_ids`.
- Prompt must instruct the model to only use provided context, never outside knowledge.
- Never delete AI response records — they are the audit trail.

### Async
- PDF ingestion is always async (enqueue to job table → worker process handles it).
- Never block an HTTP request on embedding API calls or PDF parsing.
- Worker loop uses `asyncio`. Do not use threading.

### Database
- All schema changes go through Alembic migrations. Never alter schema manually.
- Use AsyncSession everywhere. Never use synchronous SQLAlchemy sessions.
- `customer_id` must be indexed on every table that contains tenant-scoped data.
- Never hard-delete documents or chunks — soft delete using `is_active = False`.
- Worker polls with `FOR UPDATE SKIP LOCKED` — never poll without this.

### Code Style
- Type hints on all function signatures.
- One responsibility per service function.
- Use Python `logging` module. Never use `print()`.
- No raw SQL strings — SQLAlchemy ORM or `text()` with bound parameters only.

---

## Job Queue Pattern (Postgres, No Redis)

```sql
-- Worker atomically claims one job — no duplicates possible
SELECT * FROM ingestion_jobs
WHERE status = 'queued'
ORDER BY enqueued_at ASC
LIMIT 1
FOR UPDATE SKIP LOCKED;
```

Worker sleeps `WORKER_POLL_INTERVAL_SECONDS` when queue is empty, then polls again.
Document in README trade-off: production would use a dedicated queue (SQS/Redis+ARQ).

---

## Key Commands
```bash
# Start DB
docker-compose up -d

# Run migrations
alembic upgrade head

# Process 1 — API server
uvicorn app.main:app --reload --port 8000

# Process 2 — Ingestion worker
python -m app.workers.ingestion_worker

# Tests
pytest tests/ -v

# New migration
alembic revision --autogenerate -m "description"
```

---

## Environment Variables
```
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/unifize
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
JWT_SECRET=...
JWT_ALGORITHM=HS256
EMBEDDING_MODEL=text-embedding-3-small
LLM_MODEL=claude-sonnet-4-20250514
CHUNK_SIZE_TOKENS=512
CHUNK_OVERLAP_TOKENS=50
RAG_TOP_K=5
WORKER_POLL_INTERVAL_SECONDS=5
```

---

## Chunking Strategy
- 512 tokens per chunk, 50-token overlap
- Use `tiktoken` for accurate token counting
- Respect paragraph boundaries — never cut mid-sentence
- Store `chunk_index` (position in document) for ordered citations

## RAG Retrieval Strategy
- Embed query with same model used at ingestion time (`text-embedding-3-small`)
- Cosine similarity search, top-k=5, always filtered by `customer_id`
- Optional: filter by `document_ids` if user wants to scope query to specific docs
- Order results by relevance score before building prompt

---

## What NOT To Do
- Do not accept `customer_id` from user input — JWT only, always
- Do not use synchronous SQLAlchemy
- Do not use Redis or ARQ — Postgres job queue is the chosen approach
- Do not reuse DB models as API response schemas
- Do not hard-delete records — soft delete only
- Do not use `print()` for logging
- Do not store embeddings as plain float arrays — use pgvector `vector` type
- Do not run the worker inside the FastAPI process — they are separate processes
# AI Usage

This document describes how AI tooling was used during the development of this
project, in accordance with the assignment's transparency requirements.

---

## Approach & Philosophy

The most important investment in this project was upfront planning before a single
line of code was written. Before opening Claude Code, significant time was spent in
the Claude AI chat interface:

- Debating the entire architecture end to end
- Questioning every technology choice and the reasoning
- Challenging approaches and proposing alternatives

This produced a solid CLAUDE.md and PLAN.md that Claude Code read at the start of
every session. CLAUDE.md contained non-negotiable rules (tenant isolation, async
patterns, no customer_id from request body, etc.). PLAN.md had phase-by-phase tasks
with exact prompts pre-written for each phase.

Claude Code implementation started only after this plan felt complete and
satisfactory. This meant Claude Code sessions were precise and directive — "implement
exactly this" rather than "figure out what to build". The result was that Claude Code
rarely went in the wrong direction because the guardrails were already established in
CLAUDE.md before it wrote anything.

The key insight: Claude Code is only as good as the plan you give it. Spending 30%
of the total project time on planning before touching Claude Code made the remaining
70% significantly faster and produced cleaner, more reliable output.

---

## Tools Used and Purpose

Two distinct AI tools were used for two distinct purposes:

**Claude AI (chat interface, claude.ai)** — used exclusively for architecture design,
trade-off discussions, approach validation, and challenging edge cases before any code
was written. All major architectural decisions were discussed and debated here first.

**Claude Code (terminal)** — used as a coding assistant to implement the architecture
that was already designed. Handled boilerplate, scaffolding, migrations, unit tests and
implementation details. Every prompt to Claude Code was precise and directive because
the design was already decided upfront.

---

## Representative Prompts (Paraphrased)

**Claude AI (architecture/design conversations):**

- "pgvector vs a dedicated vector DB — I want to keep infrastructure simple, help me
  think through whether pgvector holds up at this scale"
- "The chunking strategy needs to balance retrieval precision with context completeness
  — what are the real trade-offs between chunk size and overlap?"
- "The audit trail needs to store the verbatim prompt, exact chunk IDs used, model
  name, temperature, and latency — anything less isn't truly replayable. Is there
  anything I'm missing that a compliance team would expect to see?"
- "The API should never touch the PDF — it accepts the upload, saves it, and hands
  off. All the heavy work belongs in a separate worker process. But I'm debating
  whether the worker should have direct DB access or receive a self-contained job
  spec. What do you think?"

**Claude Code (implementation prompts):**

- "Read CLAUDE.md and Phase 2 from PLAN.md. Implement the ingestion pipeline:
  parser.py with pdfplumber, chunker.py using tiktoken with paragraph-aware
  splitting, embedder.py with batched OpenAI calls and file_hash dedup check.
  Implement the worker using FOR UPDATE SKIP LOCKED as a standalone async process."
- "Add SOURCES_USED marker to the LLM prompt, parse it in generator.py, strip it
  before storing or returning the response, store sources_relevant as a boolean in
  the audit record."
- "Full comment sanity check across all files — fix any outdated references to manual
  run commands, Redis, or old JWT patterns."

---

## What Was Changed After Reviewing AI Output

- The docker-compose setup initially only containerised the database. After reviewing
  the setup, the API and worker running as manual terminal processes was identified as
  inconsistent — pushed to containerise all services so the entire system starts with
  a single `docker-compose up` command, including the frontend via Vite dev server
  inside a Node container.

- JWT had a dual code path after B2B auth was added — a legacy customer_id-only path
  alongside the new user_id+customer_id path. Identified this as a latent bug where
  old tokens would still validate against new endpoints. Unified to always require
  both fields, removed the legacy path and all comments referencing it entirely.

- Page-level citation required a backend change, not just a frontend label change.
  Claude Code initially just relabelled chunk indexes as "Page N" on the frontend.
  Caught this as misleading — pushed back and required a proper Alembic migration
  adding page_number to document_chunks, parser changes to track page boundaries via
  pdfplumber, and a full re-ingestion of all documents. The fix was deeper than
  Claude Code initially proposed.

---

## Rejected AI Output and Why

**1. Redis + ARQ for job queue — REJECTED**

Claude suggested Redis + ARQ as the standard job queue approach. Rejected because
spinning up Redis adds infrastructure complexity with no meaningful benefit at this
scale. Replaced with a Postgres ingestion_jobs table using FOR UPDATE SKIP LOCKED —
a production-legitimate pattern that keeps the entire stack on a single data store.
This was an independent architectural judgment call, not a suggestion from Claude Code.

**2. Unified SQLModel dual-use pattern — REJECTED**

Claude suggested using SQLModel's ability to serve as both ORM model and Pydantic API
schema to reduce boilerplate. Rejected because DB internals (file_hash, is_active,
embedding_model) must never leak to API consumers. Keeping DB models and API schemas
as separate classes enforces a clean boundary between storage and interface layers
that matters in production systems.

**3. Threshold-based source chip visibility — REJECTED TWICE**

First a relevance score threshold (0.5, then lowered to 0.3), then hardcoded phrase
matching. Both rejected because they move the brittleness to a different place rather
than solving it. Replaced with a SOURCES_USED marker in the LLM prompt — the model
self-reports whether it answered from context. This is fundamentally more reliable
because the model has full context of its own reasoning.

**4. Local sentence-transformers embedding model — REJECTED**

Claude suggested switching to intfloat/e5-large-v2 running locally to avoid OpenAI
API costs. Rejected because embedding quality directly determines retrieval quality
which determines answer quality — the core value of the entire system. In a regulated
domain demo, answer quality is non-negotiable. The cost saving was not worth the
quality trade-off. Changes were implemented and then fully reverted.

**5. Single process for API and worker — REJECTED**

Claude Code's initial scaffold ran the worker inside the FastAPI process. Rejected
because mixing fast short-lived HTTP handling with slow CPU/IO-heavy PDF processing
in one process means a heavy ingestion job can starve the event loop. Separated into
two independent Docker services (api, worker) that share the same image but have
different startup commands and failure domains.

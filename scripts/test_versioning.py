#!/usr/bin/env python3
"""End-to-end test for document versioning and update flow.

Simulates a document update scenario:
  1. Upload FDA_SOP.pdf            → should become version 1, is_active=True
  2. Upload FDA_Pharma.pdf         → renamed to FDA_SOP.pdf (same filename,
     different content = different hash = should trigger a new version)
     Expected: version 2 created, version 1 soft-deleted (is_active=False)

Prerequisites (all must be running before executing this script):
    docker-compose up -d           # DB, API at :8000, worker
    alembic upgrade head
    python scripts/seed.py         # alice@apollo.com must exist

Usage (from the project root):
    python scripts/test_versioning.py
"""

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

API_BASE = "http://localhost:8000"
SAMPLE_DIR = PROJECT_ROOT / "sample_pdf"
POLL_INTERVAL_S = 3
MAX_POLLS = 60  # 3-minute hard timeout

# ---------------------------------------------------------------------------
# Assertion tracking
# ---------------------------------------------------------------------------

_passes = 0
_fails = 0
_failed_labels: list[str] = []


def record(label: str, passed: bool, detail: str = "") -> None:
    global _passes, _fails
    if passed:
        _passes += 1
        print(f"    [PASS] {label}")
    else:
        _fails += 1
        _failed_labels.append(label)
        suffix = f"  ← {detail}" if detail else ""
        print(f"    [FAIL] {label}{suffix}")


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------


async def api_login(client: httpx.AsyncClient) -> tuple[str, str]:
    """POST /api/v1/auth/login.  Returns (Authorization header value, customer_id)."""
    resp = await client.post(
        f"{API_BASE}/api/v1/auth/login",
        json={"email": "alice@apollo.com", "password": "password123"},
    )
    if resp.status_code != 200:
        print(f"  ERROR: login failed ({resp.status_code}): {resp.text}")
        sys.exit(1)
    data = resp.json()
    print(f"  OK  email=alice@apollo.com  customer_id={data['customer_id']}")
    return f"Bearer {data['access_token']}", data["customer_id"]


async def api_upload(
    client: httpx.AsyncClient,
    filepath: Path,
    upload_filename: str,
    auth: str,
) -> tuple[str, str]:
    """POST /api/v1/sop/ingest.  Returns (job_id, document_id)."""
    with filepath.open("rb") as fh:
        content = fh.read()

    resp = await client.post(
        f"{API_BASE}/api/v1/sop/ingest",
        files={"file": (upload_filename, content, "application/pdf")},
        headers={"Authorization": auth},
        timeout=30.0,
    )
    if resp.status_code != 202:
        print(f"  ERROR: upload failed ({resp.status_code}): {resp.text}")
        sys.exit(1)
    data = resp.json()
    print(f"  OK  disk_file={filepath.name!r}  upload_name={upload_filename!r}")
    print(f"      job_id={data['job_id']}")
    print(f"      document_id={data['document_id']}")
    return data["job_id"], data["document_id"]


async def api_poll(client: httpx.AsyncClient, job_id: str, auth: str) -> str:
    """Poll GET /api/v1/sop/ingest/jobs/{id} until terminal state.

    Returns 'completed', 'failed', or 'timeout'.
    """
    print(f"  Polling every {POLL_INTERVAL_S}s (max {MAX_POLLS} attempts)...")
    for attempt in range(1, MAX_POLLS + 1):
        resp = await client.get(
            f"{API_BASE}/api/v1/sop/ingest/jobs/{job_id}",
            headers={"Authorization": auth},
        )
        if resp.status_code != 200:
            print(f"    [{attempt:2d}] poll error: {resp.status_code}")
            return "error"
        status = resp.json().get("status", "unknown")
        print(f"    [{attempt:2d}] {status}")
        if status in ("completed", "failed"):
            return status
        await asyncio.sleep(POLL_INTERVAL_S)
    return "timeout"


# ---------------------------------------------------------------------------
# DB helpers  (text() with bound params — never raw f-strings)
# ---------------------------------------------------------------------------


async def db_documents(
    db: AsyncSession, filename: str, customer_id: str
) -> list[dict]:
    """Return document rows matching filename for this tenant, ordered by version."""
    result = await db.execute(
        text("""
            SELECT filename, version, is_active, status
            FROM   documents
            WHERE  filename    = :fn
              AND  customer_id = :cid
            ORDER  BY version
        """),
        {"fn": filename, "cid": customer_id},
    )
    return [dict(r) for r in result.mappings()]


async def db_active_chunks_per_version(
    db: AsyncSession, filename: str, customer_id: str
) -> list[dict]:
    """Count *active* chunks per document version.

    The join condition includes c.is_active = TRUE so that soft-deleted
    chunks (from the superseded version) are not counted.  This is what
    determines whether stale content is still served to RAG queries.
    """
    result = await db.execute(
        text("""
            SELECT d.filename,
                   d.version,
                   d.is_active,
                   COUNT(c.id) AS chunks
            FROM   documents d
            LEFT   JOIN document_chunks c
                   ON  c.document_id = d.id
                   AND c.is_active   = TRUE
            WHERE  d.filename    = :fn
              AND  d.customer_id = :cid
            GROUP  BY d.id, d.filename, d.version, d.is_active
            ORDER  BY d.version
        """),
        {"fn": filename, "cid": customer_id},
    )
    return [dict(r) for r in result.mappings()]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    engine = create_async_engine(settings.database_url, echo=False)
    DB = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with httpx.AsyncClient() as client:

        # ── Step 1: Authenticate ─────────────────────────────────────────────
        print("\n══ Step 1: Authenticate ══════════════════════════════════════")
        auth, customer_id = await api_login(client)

        # ── Step 2: Upload FDA_SOP.pdf (first version) ───────────────────────
        print("\n══ Step 2: Upload FDA_SOP.pdf ════════════════════════════════")
        job1, doc1 = await api_upload(
            client, SAMPLE_DIR / "FDA_SOP.pdf", "FDA_SOP.pdf", auth
        )
        s1 = await api_poll(client, job1, auth)
        record("First upload completed", s1 == "completed", f"final status={s1!r}")

        # ── Step 3: DB state after first upload ──────────────────────────────
        print("\n══ Step 3: DB after first upload ═════════════════════════════")
        print("  SELECT filename, version, is_active, status")
        print("  FROM documents WHERE filename='FDA_SOP.pdf' ORDER BY version")
        async with DB() as db:
            rows1 = await db_documents(db, "FDA_SOP.pdf", customer_id)
        for r in rows1:
            print(f"    {r}")

        record("Exactly 1 row",
               len(rows1) == 1,
               f"found {len(rows1)}")
        if rows1:
            record("version = 1",
                   rows1[0]["version"] == 1,
                   f"actual={rows1[0]['version']}")
            record("is_active = True",
                   rows1[0]["is_active"] is True,
                   f"actual={rows1[0]['is_active']}")

        # ── Step 4: Upload FDA_Pharma.pdf renamed to FDA_SOP.pdf (new version) ─
        print("\n══ Step 4: Upload FDA_Pharma.pdf as 'FDA_SOP.pdf' ═══════════")
        print("  (same filename, different content → should trigger version 2)")
        job2, doc2 = await api_upload(
            client, SAMPLE_DIR / "FDA_Pharma.pdf", "FDA_SOP.pdf", auth
        )
        s2 = await api_poll(client, job2, auth)
        record("Second upload completed", s2 == "completed", f"final status={s2!r}")

        # ── Step 5: DB state after second upload — versioning check ──────────
        print("\n══ Step 5: DB after second upload (versioning check) ═════════")
        print("  SELECT filename, version, is_active, status")
        print("  FROM documents WHERE filename='FDA_SOP.pdf' ORDER BY version")
        async with DB() as db:
            rows2 = await db_documents(db, "FDA_SOP.pdf", customer_id)
        for r in rows2:
            print(f"    {r}")

        record("Exactly 2 rows",
               len(rows2) == 2,
               f"found {len(rows2)}")

        v1_docs = [r for r in rows2 if r["version"] == 1]
        v2_docs = [r for r in rows2 if r["version"] == 2]

        # Detect the specific failure mode: both rows stuck at version=1
        if len(rows2) == 2 and len(v1_docs) == 2:
            print()
            print("  NOTE: both documents have version=1 — the ingest endpoint")
            print("  never looked up the previous document, never bumped the")
            print("  version, and never soft-deleted the old record.")
            print()
            record("Old document soft-deleted (version=1, is_active=False)", False,
                   "is_active=True — old doc not marked inactive on re-upload")
            record("New document created at version=2", False,
                   "version=1 on both rows — version counter never incremented")
            record("New document is_active=True", False,
                   "no version=2 row to check")
        else:
            if v1_docs:
                record("Old document soft-deleted (version=1, is_active=False)",
                       v1_docs[0]["is_active"] is False,
                       f"actual is_active={v1_docs[0]['is_active']}")
            else:
                record("version=1 row present", False, "no version=1 row found")

            if v2_docs:
                record("New document created at version=2", True)
                record("New document is_active=True",
                       v2_docs[0]["is_active"] is True,
                       f"actual is_active={v2_docs[0]['is_active']}")
            else:
                record("New document created at version=2", False,
                       "no version=2 row — POST /sop/ingest never increments version")
                record("New document is_active=True", False,
                       "no version=2 row to check")

        # ── Step 6: Active chunk counts per version ───────────────────────────
        print("\n══ Step 6: Active chunk counts per document version ══════════")
        print("  (LEFT JOIN document_chunks ON ... AND c.is_active = TRUE)")
        async with DB() as db:
            chunk_rows = await db_active_chunks_per_version(db, "FDA_SOP.pdf", customer_id)
        for r in chunk_rows:
            print(f"    version={r['version']}  is_active={r['is_active']}"
                  f"  active_chunks={r['chunks']}")

        v1_chunks = [r for r in chunk_rows if r["version"] == 1]
        v2_chunks = [r for r in chunk_rows if r["version"] == 2]

        if len(v1_chunks) == 0:
            record("version=1 document present for chunk check", False, "no version=1 row")
        elif len(v1_chunks) == 1:
            record("version=1 has 0 active chunks (old chunks soft-deleted)",
                   v1_chunks[0]["chunks"] == 0,
                   f"actual active_chunks={v1_chunks[0]['chunks']}"
                   + (" — old chunks still active; RAG will return stale SOP content"
                      if v1_chunks[0]["chunks"] > 0 else ""))
        else:
            record("version=1 has 0 active chunks (old chunks soft-deleted)", False,
                   f"{len(v1_chunks)} documents with version=1 — versioning not implemented")

        if v2_chunks:
            record("version=2 has active chunks > 0",
                   v2_chunks[0]["chunks"] > 0,
                   f"actual active_chunks={v2_chunks[0]['chunks']}")
        else:
            record("version=2 has active chunks > 0", False,
                   "no version=2 document — versioning not implemented")

    await engine.dispose()

    # ── Summary ───────────────────────────────────────────────────────────────
    total = _passes + _fails
    print("\n══ Summary ═══════════════════════════════════════════════════════")
    print(f"  {_passes}/{total} assertions passed")

    if _fails == 0:
        print("  ✓ ALL PASSED — document versioning works correctly")
        return

    print(f"  ✗ {_fails} FAILED:")
    for label in _failed_labels:
        print(f"      • {label}")

    print()
    print("  ── What needs to be implemented ──────────────────────────────")
    print()
    print("  File: app/api/v1/ingest.py  (POST /sop/ingest handler)")
    print()
    print("  Before creating the new Document record, look up the current")
    print("  active document with the same filename for this customer:")
    print()
    print("    existing = await db.execute(")
    print("        select(Document)")
    print("        .where(")
    print("            Document.customer_id == customer_id,")
    print("            Document.filename    == original_filename,")
    print("            Document.is_active.is_(True),")
    print("        )")
    print("        .order_by(Document.version.desc())")
    print("        .limit(1)")
    print("    )")
    print("    prev = existing.scalars().first()")
    print()
    print("  If prev exists:")
    print("    prev.is_active = False          # soft-delete old version")
    print("    new_version    = prev.version + 1")
    print("  Else:")
    print("    new_version    = 1")
    print()
    print("  Pass new_version when constructing the Document object.")
    print()
    print("  File: app/services/ingestion/embedder.py  (upsert_chunks)")
    print()
    print("  After embedding the new version, soft-delete old version's chunks")
    print("  so RAG queries don't return stale SOP content:")
    print()
    print("    # Accept optional prev_document_id argument")
    print("    if prev_document_id:")
    print("        old_chunks = await db.execute(")
    print("            select(DocumentChunk).where(")
    print("                DocumentChunk.document_id == prev_document_id,")
    print("                DocumentChunk.is_active.is_(True),")
    print("            )")
    print("        )")
    print("        for c in old_chunks.scalars():")
    print("            c.is_active = False")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except httpx.ConnectError:
        print("\n  ERROR: Could not connect to http://localhost:8000")
        print("  Make sure docker-compose is running: docker-compose up -d")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n  Interrupted.")
        sys.exit(1)

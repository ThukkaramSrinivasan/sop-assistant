"""Prompt builder for the RAG pipeline.

Single public function:
  build_prompt — assembles the full prompt from retrieved chunks and the user query.

The returned string is stored verbatim in ai_responses.prompt_sent for auditability.
What is stored is exactly what is sent to the LLM — no hidden transformations.
"""

from app.services.rag.retriever import RetrievedChunk


def build_prompt(query: str, chunks: list[RetrievedChunk]) -> str:
    """Assemble the full prompt from the retrieved context chunks and user query.

    Structure:
      - System instructions: role definition + strict constraint to use only provided context
      - Numbered source blocks: each chunk labelled with filename and section index
      - User query at the end

    The [Source N] notation in the instructions matches the block headers so the
    model can produce verifiable inline citations.
    """
    source_blocks = "\n\n".join(
        f"[Source {i} — {chunk.document_filename}, section {chunk.chunk_index}]\n"
        f"{chunk.chunk_text}"
        for i, chunk in enumerate(chunks, start=1)
    )

    if not source_blocks:
        source_blocks = "[No context documents available]"

    return (
        "System:\n"
        "You are an AI assistant that analyzes Standard Operating Procedures (SOPs).\n"
        "Use ONLY the context provided below. Do not use any outside knowledge.\n"
        "If the answer is not in the context, explicitly say so.\n"
        "Always cite sources using [Source N] notation.\n"
        "After your answer, on a new line, output exactly this format:\n"
        "SOURCES_USED: true\n"
        "or\n"
        "SOURCES_USED: false\n"
        "Output true if your answer was based on the provided context. "
        "Output false if the question was out of scope or unanswerable from context.\n"
        "\n"
        "Context:\n"
        f"{source_blocks}\n"
        "\n"
        f"User Query: {query}"
    )

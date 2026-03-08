"""Prompt builder for the RAG pipeline.

Single public function:
  build_prompt — assembles the full prompt from retrieved chunks and the user query.

The returned string is stored verbatim in ai_responses.prompt_sent for auditability.
What is stored is exactly what is sent to the LLM — no hidden transformations.
"""

from app.services.rag.retriever import RetrievedChunk

_HISTORY_CAP = 6  # max messages (3 turns) injected into prompt


def build_prompt(
    query: str,
    chunks: list[RetrievedChunk],
    conversation_history: list | None = None,
) -> str:
    """Assemble the full prompt from the retrieved context chunks and user query.

    Structure:
      - System instructions: role definition + strict constraint to use only provided context
        (+ pronoun-resolution instruction when conversation_history is provided)
      - Numbered source blocks: each chunk labelled with filename and section index
      - Conversation history block (only if conversation_history is non-empty)
      - Current question (or "User Query" for single-turn queries)

    The [Source N] notation in the instructions matches the block headers so the
    model can produce verifiable inline citations.

    Single-turn queries (empty or None conversation_history) produce an identical
    prompt to the pre-conversation implementation — no behaviour change.
    """
    source_blocks = "\n\n".join(
        f"[Source {i} — {chunk.document_filename}, section {chunk.chunk_index}]\n"
        f"{chunk.chunk_text}"
        for i, chunk in enumerate(chunks, start=1)
    )

    if not source_blocks:
        source_blocks = "[No context documents available]"

    # Cap history at the last _HISTORY_CAP messages (trim from front).
    history = list(conversation_history or [])
    if len(history) > _HISTORY_CAP:
        history = history[-_HISTORY_CAP:]

    # Extra system instruction only injected when there is prior context.
    pronoun_instruction = ""
    if history:
        pronoun_instruction = (
            "Use the conversation history to resolve pronouns and "
            "references (e.g. 'it', 'they', 'this process') from "
            "previous messages. Do not answer from history alone — "
            "always ground your answer in the provided context.\n"
        )

    # Build the user-facing section: conversation block + current question.
    if history:
        history_lines = "\n".join(
            f"{msg['role'] if isinstance(msg, dict) else msg.role}: "
            f"{msg['content'] if isinstance(msg, dict) else msg.content}"
            for msg in history
        )
        user_section = (
            f"Conversation so far:\n{history_lines}\n\n"
            f"Current question: {query}"
        )
    else:
        user_section = f"User Query: {query}"

    return (
        "System:\n"
        "You are an AI assistant that analyzes Standard Operating Procedures (SOPs).\n"
        "Use ONLY the context provided below. Do not use any outside knowledge.\n"
        "If the answer is not in the context, explicitly say so.\n"
        "Always cite sources using [Source N] notation.\n"
        + pronoun_instruction
        + "After your answer, on a new line, output exactly this format:\n"
        "SOURCES_USED: true\n"
        "or\n"
        "SOURCES_USED: false\n"
        "Output true if your answer was based on the provided context. "
        "Output false if the question was out of scope or unanswerable from context.\n"
        "\n"
        "Context:\n"
        f"{source_blocks}\n"
        "\n"
        f"{user_section}"
    )

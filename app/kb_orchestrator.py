"""
Simple knowledge base orchestrator for LangGraph.

This module exposes a single function, kb_orchestrator, which is suitable
for use as a LangGraph node. It builds a short natural-language query from
the current GraphState, embeds it with OpenAI using the same model as the
Phase 2 kb_index CLI, and performs a pgvector similarity search against
kb.policies to retrieve relevant policy snippets.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from openai import OpenAI
import psycopg
from pgvector.psycopg import register_vector

from app.state import GraphState


EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_K = 3


def _get_kb_dsn() -> str:
    """
    Resolve the Postgres DSN for KB access.

    Follows the same precedence as the kb_index CLI:
    1. KB_PG_DSN
    2. POSTGRES_DSN
    """
    env_dsn = os.getenv("KB_PG_DSN") or os.getenv("POSTGRES_DSN")
    if not env_dsn:
        raise RuntimeError(
            "Postgres DSN for KB must be provided via KB_PG_DSN or POSTGRES_DSN."
        )
    return env_dsn


def _build_query_from_state(state: GraphState) -> str:
    """
    Build a short natural-language query from the graph state.
    Uses issue_type, ticket_text, and any available evidence['order'] fields.
    """
    issue_type = state.get("issue_type") or "unknown"
    ticket_text = (state.get("ticket_text") or "").strip()

    evidence = state.get("evidence") or {}
    order: Optional[Dict[str, Any]] = evidence.get("order") or {}

    parts: List[str] = []
    parts.append(f"Issue type: {issue_type}.")
    if ticket_text:
        parts.append(f"Ticket: {ticket_text}")

    order_id = order.get("order_id")
    product = order.get("product") or order.get("product_name")
    if order_id or product:
        details: List[str] = []
        if order_id:
            details.append(f"order_id {order_id}")
        if product:
            details.append(f"product {product}")
        parts.append("Order details: " + ", ".join(details) + ".")

    return " ".join(parts)


def _embed_query(client: OpenAI, query: str) -> List[float]:
    """Embed the natural-language query using the same model as kb_index."""
    if not query.strip():
        raise ValueError("Query text for KB retrieval is empty.")

    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=query,
    )
    # Single input, so we expect a single embedding in data[0].
    return response.data[0].embedding


def _search_policies(
    dsn: str,
    query_embedding: List[float],
    k: int = DEFAULT_K,
) -> List[Dict[str, Any]]:
    """
    Run a pgvector similarity search against kb.policies.

    Returns a list of rows containing doc_id, file, chunk_index, and content.
    """
    results: List[Dict[str, Any]] = []

    with psycopg.connect(dsn) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT doc_id, file, chunk_index, content
                FROM kb.policies
                ORDER BY embedding <-> %s
                LIMIT %s
                """,
                (query_embedding, k),
            )
            for doc_id, file, chunk_index, content in cur.fetchall():
                results.append(
                    {
                        "doc_id": doc_id,
                        "file": file,
                        "chunk_index": int(chunk_index) if chunk_index is not None else None,
                        "content": content,
                    }
                )

    return results


def kb_orchestrator(state: GraphState) -> GraphState:
    """
    LangGraph node that performs a simple semantic retrieval over kb.policies.

    It:
    - Builds a short query from issue_type, ticket_text, and evidence['order'].
    - Embeds the query with OpenAI using the same model as the kb_index CLI.
    - Runs a pgvector similarity search on kb.policies.
    - Attaches policy_citations to state['evidence'] and returns the updated state.
    """
    # Build query from current state
    query = _build_query_from_state(state)

    # Embed query
    client = OpenAI()
    embedding = _embed_query(client, query)

    # Run similarity search against kb.policies
    dsn = _get_kb_dsn()
    rows = _search_policies(dsn, embedding, k=DEFAULT_K)

    # Prepare citations with a short snippet from each content
    citations: List[Dict[str, Any]] = []
    for row in rows:
        content = row.get("content") or ""
        # Simple snippet: first 200 characters
        snippet = content[:200]
        citations.append(
            {
                "file": row.get("file"),
                "doc_id": row.get("doc_id"),
                "chunk_index": row.get("chunk_index"),
                "snippet": snippet,
            }
        )

    # Attach to evidence and return updated state
    evidence = state.get("evidence") or {}
    evidence["policy_citations"] = citations

    return {
        **state,
        "evidence": evidence,
    }


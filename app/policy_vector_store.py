"""
Minimal pgvector-backed store for policy chunks and a thin embedding wrapper.
"""
from __future__ import annotations

import os
from typing import Any, Iterable, List, Mapping, Sequence, Dict


# Environment-driven configuration
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/triage",
)


def ensure_policy_table_exists(conn: Any) -> None:
    """
    Ensure the pgvector extension and policy_chunks table exist.

    Expected schema:
      id SERIAL PRIMARY KEY,
      file_name TEXT,
      section_id TEXT,
      content TEXT,
      embedding VECTOR(EMBEDDING_DIM)
    """
    with conn.cursor() as cur:
        # Enable pgvector extension (no-op if already installed)
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS policy_chunks (
                id SERIAL PRIMARY KEY,
                file_name TEXT NOT NULL,
                section_id TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding VECTOR({EMBEDDING_DIM}) NOT NULL
            );
            """
        )
        # Stable upsert key for each (file_name, section_id) pair
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_policy_chunks_file_section
            ON policy_chunks (file_name, section_id);
            """
        )
    conn.commit()


def _to_pgvector_literal(embedding: Sequence[float]) -> str:
    """Convert a list of floats to a pgvector-compatible literal string."""
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"


def upsert_policy_chunks(conn: Any, chunks_with_embeddings: Iterable[Mapping[str, Any]]) -> None:
    """
    Upsert policy chunks with embeddings into the policy_chunks table.

    Each chunk mapping must include:
      - file_name: str
      - section_id: str
      - content: str
      - embedding: Sequence[float]
    """
    items = list(chunks_with_embeddings)
    if not items:
        return

    records: List[tuple] = []
    for chunk in items:
        file_name = chunk["file_name"]
        section_id = chunk["section_id"]
        content = chunk["content"]
        embedding = chunk["embedding"]
        records.append(
            (
                file_name,
                section_id,
                content,
                _to_pgvector_literal(embedding),
            )
        )

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO policy_chunks (file_name, section_id, content, embedding)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (file_name, section_id) DO UPDATE SET
                content = EXCLUDED.content,
                embedding = EXCLUDED.embedding;
            """,
            records,
        )
    conn.commit()


def query_policies(text: str, k: int = 3) -> List[Dict[str, Any]]:
    """
    Query the policy_chunks table for the top-k nearest chunks to the input text.

    Returns a list of dicts:
      {file_name, section_id, content, score}
    """
    if not text:
        return []

    client = EmbeddingClient()
    embeddings = client.embed([text])
    if not embeddings:
        return []

    query_embedding = embeddings[0]
    vector_literal = _to_pgvector_literal(query_embedding)

    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "The 'psycopg' package is required for policy retrieval. "
            "Install it with `pip install psycopg[binary]` or similar."
        ) from exc

    results: List[Dict[str, Any]] = []
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id,
                       file_name,
                       section_id,
                       content,
                       (embedding <-> %s::vector) AS score
                FROM policy_chunks
                ORDER BY embedding <-> %s::vector
                LIMIT %s;
                """,
                (vector_literal, vector_literal, k),
            )
            rows = cur.fetchall()

    for row_id, file_name, section_id, content, score in rows:
        results.append(
            {
                "id": int(row_id) if row_id is not None else None,
                "file_name": file_name,
                "section_id": section_id,
                "content": content,
                "score": float(score) if score is not None else None,
            }
        )

    return results


class EmbeddingClient:
    """
    Tiny embedding client that wraps a single embedding model.

    Configuration:
      - OPENAI_API_KEY: API key for the provider
      - EMBEDDING_MODEL: model identifier (default: text-embedding-3-small)
    """

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        self._model = model or EMBEDDING_MODEL
        self._api_key = api_key or OPENAI_API_KEY

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        """
        Generate embeddings for a list of strings.

        Returns a list-of-floats per input string.
        """
        if not texts:
            return []

        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")

        try:
            from openai import OpenAI  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "The 'openai' package is required for EmbeddingClient. "
                "Install it with `pip install openai`."
            ) from exc

        client = OpenAI(api_key=self._api_key)
        response = client.embeddings.create(model=self._model, input=list(texts))
        return [d.embedding for d in response.data]


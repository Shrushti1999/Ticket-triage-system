"""
CLI to index policy markdown files into a pgvector-backed policy_chunks table.

Run with:
    python -m app.kb_index --kb-dir NewPhase/policies --reset
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, Dict, List

import psycopg

from app.policy_vector_store import (
    EmbeddingClient,
    ensure_policy_table_exists,
    upsert_policy_chunks,
)


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/triage",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Index markdown policies into the policy_chunks pgvector table."
    )
    parser.add_argument(
        "--kb-dir",
        type=str,
        default="NewPhase/policies",
        help="Directory containing *.md policy files (default: NewPhase/policies).",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Truncate policy_chunks table before indexing.",
    )
    return parser.parse_args()


def _resolve_kb_dir(kb_dir: str) -> Path:
    """Resolve the KB directory relative to the project root if needed."""
    kb_path = Path(kb_dir)
    if kb_path.is_absolute():
        return kb_path

    root = Path(__file__).resolve().parent.parent
    return (root / kb_path).resolve()


def _load_policy_chunks(kb_dir: Path) -> List[Dict[str, Any]]:
    """
    Load all *.md files and split into deterministic sections.

    Strategy:
      - One chunk per non-empty line after the first H1.
      - section_id is <file_stem>#<n>, starting at 1.
    """
    chunks: List[Dict[str, Any]] = []

    for path in sorted(kb_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        if not lines:
            continue

        # Skip the first H1 line and any immediately following blank lines.
        idx = 1  # start after line 0 (H1)
        while idx < len(lines) and not lines[idx].strip():
            idx += 1

        stem = path.stem
        section_counter = 1
        while idx < len(lines):
            line = lines[idx].strip()
            idx += 1
            if not line:
                continue

            section_id = f"{stem}#{section_counter}"
            section_counter += 1

            chunks.append(
                {
                    "file_name": path.name,
                    "section_id": section_id,
                    "content": line,
                }
            )

    return chunks


def main() -> None:
    args = _parse_args()
    kb_dir = _resolve_kb_dir(args.kb_dir)

    if not kb_dir.exists() or not kb_dir.is_dir():
        raise SystemExit(f"KB directory does not exist or is not a directory: {kb_dir}")

    policy_chunks = _load_policy_chunks(kb_dir)
    if not policy_chunks:
        print(f"No policy chunks found in {kb_dir}")
        return

    embedding_client = EmbeddingClient()
    texts = [c["content"] for c in policy_chunks]
    embeddings = embedding_client.embed(texts)
    if len(embeddings) != len(policy_chunks):
        raise RuntimeError("Embedding count does not match number of policy chunks.")

    for chunk, embedding in zip(policy_chunks, embeddings):
        chunk["embedding"] = embedding

    with psycopg.connect(DATABASE_URL) as conn:
        ensure_policy_table_exists(conn)

        if args.reset:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE policy_chunks;")
            conn.commit()

        upsert_policy_chunks(conn, policy_chunks)

    print(f"Indexed {len(policy_chunks)} policy chunks from {kb_dir} into policy_chunks.")


if __name__ == "__main__":
    main()


#!/usr/bin/env python3
import argparse
import glob
import os
from typing import List, Tuple

from openai import OpenAI
import psycopg
from pgvector.psycopg import register_vector


def chunk_text(text: str, size: int) -> List[str]:
    """Chunk text by character count, respecting line boundaries."""
    buffer: str = ""
    parts: List[str] = []
    for line in text.splitlines(keepends=True):
        if len(buffer) + len(line) > size:
            if buffer:
                parts.append(buffer)
            buffer = ""
        buffer += line
    if buffer:
        parts.append(buffer)
    return parts


def discover_policy_files(policies_dir: str) -> List[str]:
    pattern = os.path.join(policies_dir, "*.md")
    return sorted(glob.glob(pattern))


def get_dsn(cli_dsn: str | None) -> str:
    if cli_dsn:
        return cli_dsn
    env_dsn = os.getenv("KB_PG_DSN") or os.getenv("POSTGRES_DSN")
    if not env_dsn:
        raise SystemExit(
            "Postgres DSN must be provided via --dsn, KB_PG_DSN, or POSTGRES_DSN."
        )
    return env_dsn


def ensure_schema_and_table(conn: psycopg.Connection, recreate: bool) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS kb")
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        if recreate:
            cur.execute("DROP TABLE IF EXISTS kb.policies")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS kb.policies (
                id SERIAL PRIMARY KEY,
                doc_id TEXT,
                file TEXT,
                chunk_index INT,
                content TEXT,
                embedding vector(1536)
            )
            """
        )
    conn.commit()


def embed_chunks(client: OpenAI, chunks: List[str]) -> List[List[float]]:
    if not chunks:
        return []
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=chunks,
    )
    # The API returns embeddings in the same order as the inputs.
    return [d.embedding for d in response.data]


def index_policies(
    policies_dir: str,
    dsn: str,
    recreate: bool,
    chunk_size: int,
) -> Tuple[int, List[Tuple[str, int]]]:
    files = discover_policy_files(policies_dir)
    if not files:
        print(f"No policy markdown files found in {policies_dir}.")
        return 0, []

    client = OpenAI()

    with psycopg.connect(dsn) as conn:
        register_vector(conn)
        ensure_schema_and_table(conn, recreate=recreate)

        total_chunks = 0
        per_file_counts: List[Tuple[str, int]] = []

        with conn.cursor() as cur:
            for path in files:
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read()

                chunks = chunk_text(text, size=chunk_size)
                embeddings = embed_chunks(client, chunks)

                filename = os.path.basename(path)
                rel_path = os.path.relpath(path, policies_dir)
                file_chunks = 0

                for idx, (content, emb) in enumerate(zip(chunks, embeddings)):
                    doc_id = f"{filename}#chunk-{idx+1}"
                    cur.execute(
                        """
                        INSERT INTO kb.policies
                            (doc_id, file, chunk_index, content, embedding)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (doc_id, rel_path, idx, content, emb),
                    )
                    file_chunks += 1
                    total_chunks += 1

                per_file_counts.append((rel_path, file_chunks))

        conn.commit()

    return total_chunks, per_file_counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Index policy markdown files into Postgres with pgvector embeddings."
    )
    parser.add_argument(
        "--policies-dir",
        default="Phase2/mock_data/policies",
        help="Directory containing policy .md files (default: Phase2/mock_data/policies)",
    )
    parser.add_argument(
        "--dsn",
        default=None,
        help="Postgres DSN. If omitted, KB_PG_DSN or POSTGRES_DSN is used.",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Drop and recreate kb.policies table before indexing.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=400,
        help="Maximum characters per text chunk (default: 400).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dsn = get_dsn(args.dsn)

    total_chunks, per_file_counts = index_policies(
        policies_dir=args.policies_dir,
        dsn=dsn,
        recreate=bool(args.recreate),
        chunk_size=args.chunk_size,
    )

    if total_chunks == 0:
        return

    print(f"Indexed {total_chunks} chunks from {len(per_file_counts)} files into kb.policies.")
    for file_path, count in per_file_counts:
        print(f"- {file_path}: {count} chunks")


if __name__ == "__main__":
    main()
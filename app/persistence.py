"""
Pending tickets persistence: Postgres table (same DB as checkpointer) or in-memory store for tests.
"""
from __future__ import annotations

from typing import Any, Optional

# Table schema (same DB as checkpointer)
PENDING_TICKETS_TABLE = """
CREATE TABLE IF NOT EXISTS pending_tickets (
    ticket_id TEXT PRIMARY KEY,
    order_id TEXT,
    issue_type TEXT,
    recommendation TEXT,
    status TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""


class MemoryPendingTicketsStore:
    """In-memory store for pending tickets (used in tests or when patched)."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def setup(self) -> None:
        """No-op for in-memory store."""
        pass

    def add_pending(
        self,
        ticket_id: str,
        *,
        order_id: Optional[str] = None,
        issue_type: Optional[str] = None,
        recommendation: Optional[str] = None,
        status: Optional[str] = None,
    ) -> None:
        self._store[ticket_id] = {
            "ticket_id": ticket_id,
            "order_id": order_id,
            "issue_type": issue_type,
            "recommendation": recommendation,
            "status": status or "awaiting_admin",
        }

    def remove_pending(self, ticket_id: str) -> None:
        self._store.pop(ticket_id, None)

    def list_pending(self) -> list[dict[str, Any]]:
        return list(self._store.values())

    def is_pending(self, ticket_id: str) -> bool:
        return ticket_id in self._store


class PostgresPendingTicketsStore:
    """Postgres-backed store for pending tickets (same DB as checkpointer)."""

    def __init__(self, conn_string: str) -> None:
        self._conn_string = conn_string

    def setup(self) -> None:
        import psycopg
        with psycopg.connect(self._conn_string) as conn:
            with conn.cursor() as cur:
                cur.execute(PENDING_TICKETS_TABLE)
            conn.commit()

    def add_pending(
        self,
        ticket_id: str,
        *,
        order_id: Optional[str] = None,
        issue_type: Optional[str] = None,
        recommendation: Optional[str] = None,
        status: Optional[str] = None,
    ) -> None:
        import psycopg
        with psycopg.connect(self._conn_string) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pending_tickets (ticket_id, order_id, issue_type, recommendation, status)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (ticket_id) DO UPDATE SET
                        order_id = EXCLUDED.order_id,
                        issue_type = EXCLUDED.issue_type,
                        recommendation = EXCLUDED.recommendation,
                        status = EXCLUDED.status
                    """,
                    (ticket_id, order_id, issue_type, recommendation, status or "awaiting_admin"),
                )
            conn.commit()

    def remove_pending(self, ticket_id: str) -> None:
        import psycopg
        with psycopg.connect(self._conn_string) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM pending_tickets WHERE ticket_id = %s", (ticket_id,))
            conn.commit()

    def list_pending(self) -> list[dict[str, Any]]:
        import psycopg
        with psycopg.connect(self._conn_string) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT ticket_id, order_id, issue_type, recommendation, status FROM pending_tickets ORDER BY created_at"
                )
                rows = cur.fetchall()
        return [
            {
                "ticket_id": r[0],
                "order_id": r[1],
                "issue_type": r[2],
                "recommendation": r[3],
                "status": r[4],
            }
            for r in rows
        ]

    def is_pending(self, ticket_id: str) -> bool:
        import psycopg
        with psycopg.connect(self._conn_string) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pending_tickets WHERE ticket_id = %s", (ticket_id,))
                return cur.fetchone() is not None

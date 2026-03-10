import json
from dataclasses import dataclass
from typing import Dict, Optional

import psycopg


@dataclass
class PendingTicket:
    ticket_id: str
    status: str
    issue_type: Optional[str]
    order_id: Optional[str]
    recommendation: Optional[str]


class PostgresPendingTicketStore:
    """
    Simple persistence layer for pending tickets backed by Postgres.

    Uses the same database as the LangGraph Postgres checkpointer.
    """

    def __init__(self, dsn: str):
        self._dsn = dsn
        self._ensure_table()

    def _get_conn(self):
        return psycopg.connect(self._dsn, autocommit=True)

    def _ensure_table(self):
        with self._get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_tickets (
                    ticket_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    issue_type TEXT,
                    order_id TEXT,
                    recommendation TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )

    def upsert(self, ticket: PendingTicket) -> None:
        with self._get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO pending_tickets (ticket_id, status, issue_type, order_id, recommendation)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (ticket_id)
                DO UPDATE SET
                    status = EXCLUDED.status,
                    issue_type = EXCLUDED.issue_type,
                    order_id = EXCLUDED.order_id,
                    recommendation = EXCLUDED.recommendation
                """,
                (
                    ticket.ticket_id,
                    ticket.status,
                    ticket.issue_type,
                    ticket.order_id,
                    ticket.recommendation,
                ),
            )

    def delete(self, ticket_id: str) -> None:
        with self._get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM pending_tickets WHERE ticket_id = %s", (ticket_id,))

    def get(self, ticket_id: str) -> Optional[PendingTicket]:
        with self._get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT ticket_id, status, issue_type, order_id, recommendation
                FROM pending_tickets
                WHERE ticket_id = %s
                """,
                (ticket_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return PendingTicket(
                ticket_id=row[0],
                status=row[1],
                issue_type=row[2],
                order_id=row[3],
                recommendation=row[4],
            )

    def list_pending(self) -> Dict[str, PendingTicket]:
        result: Dict[str, PendingTicket] = {}
        with self._get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT ticket_id, status, issue_type, order_id, recommendation
                FROM pending_tickets
                ORDER BY created_at ASC
                """
            )
            for row in cur.fetchall():
                ticket = PendingTicket(
                    ticket_id=row[0],
                    status=row[1],
                    issue_type=row[2],
                    order_id=row[3],
                    recommendation=row[4],
                )
                result[ticket.ticket_id] = ticket
        return result


class InMemoryPendingTicketStore:
    """
    In-memory implementation used for tests.
    """

    def __init__(self):
        self._tickets: Dict[str, PendingTicket] = {}

    def upsert(self, ticket: PendingTicket) -> None:
        self._tickets[ticket.ticket_id] = ticket

    def delete(self, ticket_id: str) -> None:
        self._tickets.pop(ticket_id, None)

    def get(self, ticket_id: str) -> Optional[PendingTicket]:
        return self._tickets.get(ticket_id)

    def list_pending(self) -> Dict[str, PendingTicket]:
        return dict(self._tickets)


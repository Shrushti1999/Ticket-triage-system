CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS pending_tickets (
    ticket_id TEXT PRIMARY KEY,
    order_id TEXT,
    issue_type TEXT,
    recommendation TEXT,
    status TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

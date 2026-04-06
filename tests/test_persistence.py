"""
Persistence tests: MemorySaver in lifespan, TestClient(app), in-memory pending store.

Run with USE_MEMORY_SAVER=1 so the app uses MemorySaver and MemoryPendingTicketsStore
(no Postgres required). Optionally patch persistence to a dedicated in-memory store.
"""
import os

# Use MemorySaver in lifespan before app is imported (so TestClient gets in-memory checkpointer)
os.environ["USE_MEMORY_SAVER"] = "1"

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.persistence import MemoryPendingTicketsStore


# Sample order for mocking order fetch
SAMPLE_ORDER = {
    "order_id": "ORD1001",
    "customer_name": "Ava Chen",
    "email": "ava.chen@example.com",
    "items": [{"sku": "SKU-100-A", "name": "Wireless Mouse", "quantity": 1}],
    "order_date": "2025-01-08",
    "status": "delivered",
    "delivery_date": "2025-01-12",
    "total_amount": 45.99,
    "currency": "USD",
}


@pytest.fixture
def mock_order_response():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = SAMPLE_ORDER
    mock_response.raise_for_status = MagicMock()
    return mock_response


@pytest.fixture
def mock_httpx_client(mock_order_response):
    """Mock httpx so order fetch does not hit the network."""
    with patch("app.tools.httpx.Client") as mock_client:
        mock_instance = MagicMock()
        mock_instance.__enter__.return_value = mock_instance
        mock_instance.__exit__.return_value = None
        mock_instance.get.return_value = mock_order_response
        mock_client.return_value = mock_instance
        yield mock_instance


class TestPersistenceWithMemorySaver:
    """Use MemorySaver in lifespan and TestClient(app)."""

    def test_triage_invoke_pending_and_review(self, mock_httpx_client):
        """Full flow: invoke -> pending list -> review; state is checkpointed and resumable."""
        with TestClient(app) as client:
            r = client.post(
                "/triage/invoke",
                json={"ticket_text": "I need a refund for ORD1001", "order_id": "ORD1001"},
            )
            assert r.status_code == 200, r.text
            data = r.json()
            ticket_id = data["ticket_id"]
            assert data["status"] == "awaiting_approval"

            pending = client.get("/triage/pending").json()
            assert pending["count"] >= 1
            ids = [t["ticket_id"] for t in pending["pending_tickets"]]
            assert ticket_id in ids

            review_r = client.post(
                "/triage/review",
                json={"ticket_id": ticket_id, "decision": "approve"},
            )
            assert review_r.status_code == 200
            assert review_r.json()["status"] == "completed"

            pending_after = client.get("/triage/pending").json()
            assert pending_after["count"] == pending["count"] - 1
            assert ticket_id not in [t["ticket_id"] for t in pending_after["pending_tickets"]]

    def test_deterministic_ticket_id(self, mock_httpx_client):
        """Same ticket_text + order_id produces the same ticket_id (resumable)."""
        payload = {"ticket_text": "Refund please ORD1001", "order_id": "ORD1001"}
        with TestClient(app) as client:
            r1 = client.post("/triage/invoke", json=payload)
            assert r1.status_code == 200
            ticket_id_1 = r1.json()["ticket_id"]

            r2 = client.post("/triage/invoke", json=payload)
            assert r2.status_code == 200
            ticket_id_2 = r2.json()["ticket_id"]

            assert ticket_id_1 == ticket_id_2

    def test_get_state_returns_checkpointed_values(self, mock_httpx_client):
        """After triage invoke, get_state(thread_id) returns the checkpointed state."""
        with TestClient(app) as client:
            r = client.post(
                "/triage/invoke",
                json={"ticket_text": "I need a refund for ORD1001"},
            )
            assert r.status_code == 200
            ticket_id = r.json()["ticket_id"]

            snapshot = client.app.state.triage_graph.get_state(
                {"configurable": {"thread_id": ticket_id}}
            )
            assert snapshot.values is not None
            state = dict(snapshot.values)
            assert state.get("issue_type") == "refund_request"
            assert state.get("refund_preview") is not None
            assert state.get("status") == "awaiting_approval"

    def test_review_loads_state_via_get_state(self, mock_httpx_client):
        """Review uses triage_graph.get_state(thread_id) then invokes admin graph."""
        with TestClient(app) as client:
            r = client.post(
                "/triage/invoke",
                json={"ticket_text": "Refund ORD1001", "order_id": "ORD1001"},
            )
            assert r.status_code == 200
            ticket_id = r.json()["ticket_id"]

            review_r = client.post(
                "/triage/review",
                json={"ticket_id": ticket_id, "decision": "reject", "feedback": "Need more info"},
            )
            assert review_r.status_code == 200
            assert review_r.json()["status"] == "completed"

    def test_patch_persistence_to_in_memory_store(self, mock_httpx_client):
        """Patch app.state.pending_store to a dedicated in-memory store and assert on it."""
        with TestClient(app) as client:
            store = MemoryPendingTicketsStore()
            client.app.state.pending_store = store

            r = client.post(
                "/triage/invoke",
                json={"ticket_text": "Refund ORD1001"},
            )
            assert r.status_code == 200
            ticket_id = r.json()["ticket_id"]

            assert len(store.list_pending()) == 1
            listed = store.list_pending()[0]
            assert listed["ticket_id"] == ticket_id
            assert store.is_pending(ticket_id)

            client.post("/triage/review", json={"ticket_id": ticket_id, "decision": "approve"})
            assert not store.is_pending(ticket_id)
            assert len(store.list_pending()) == 0

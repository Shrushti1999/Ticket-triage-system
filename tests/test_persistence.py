import hashlib

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from app.main import app
from app.persistence import InMemoryPendingTicketStore


@pytest.fixture(autouse=True)
def setup_in_memory_persistence(monkeypatch):
    """
    Use MemorySaver checkpointer and in-memory pending ticket store for tests.
    """

    # Swap pending_store to in-memory implementation
    in_memory_store = InMemoryPendingTicketStore()
    app.state.pending_store = in_memory_store

    # Replace lifespan to use MemorySaver instead of PostgresSaver
    from app import graph

    def create_memory_graphs():
        memory = MemorySaver()
        triage = graph.create_triage_graph(checkpointer=memory)
        admin = graph.create_admin_review_graph(checkpointer=memory)
        return triage, admin

    triage_graph, admin_review_graph = create_memory_graphs()
    app.state.triage_graph = triage_graph
    app.state.admin_review_graph = admin_review_graph

    yield


def _deterministic_ticket_id(ticket_text: str, order_id: str | None) -> str:
    payload = f"{ticket_text}|{order_id or ''}"
    return hashlib.md5(payload.encode()).hexdigest()[:8]


def test_ticket_persistence_and_resume_flow():
    """
    End-to-end test using TestClient and in-memory persistence.
    Verifies that:
    - a triage invoke creates a pending ticket entry
    - the same ticket_id is used as thread_id
    - admin review loads state via get_state and completes the workflow
    """
    client = TestClient(app)

    ticket_text = "I need a refund for ORD1001"
    order_id = None
    expected_ticket_id = _deterministic_ticket_id(ticket_text, order_id)

    # 1. Invoke triage
    resp = client.post(
        "/triage/invoke",
        json={"ticket_text": ticket_text, "order_id": order_id},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ticket_id"] == expected_ticket_id
    assert data["status"] == "awaiting_admin"

    # 2. Check pending tickets endpoint
    pending_resp = client.get("/triage/pending")
    assert pending_resp.status_code == 200
    pending_data = pending_resp.json()
    assert pending_data["count"] == 1
    assert pending_data["pending_tickets"][0]["ticket_id"] == expected_ticket_id

    # 3. Perform admin review (approve)
    review_resp = client.post(
        "/triage/review",
        json={"ticket_id": expected_ticket_id, "decision": "approve"},
    )
    assert review_resp.status_code == 200
    review_data = review_resp.json()
    assert review_data["ticket_id"] == expected_ticket_id
    assert review_data["status"] == "completed"

    # 4. Pending list should now be empty
    pending_resp2 = client.get("/triage/pending")
    assert pending_resp2.status_code == 200
    pending_data2 = pending_resp2.json()
    assert pending_data2["count"] == 0


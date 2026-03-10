"""
FastAPI application for Ticket Triage System.

Three-entity workflow:
- Customer: POST /triage/invoke - Submit a support ticket
- Assistant: Automatically processes and drafts recommendation
- Admin: POST /triage/review - Approve or reject the recommendation
"""
from contextlib import asynccontextmanager
import json
import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from pydantic import BaseModel

from app.graph import create_triage_graph, create_admin_review_graph
from app.persistence import InMemoryPendingTicketStore, PostgresPendingTicketStore, PendingTicket


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context.

    Initializes a single PostgresSaver checkpointer and compiles graphs with it,
    keeping them alive for the entire app lifetime.
    """
    dsn = os.getenv("POSTGRES_DSN", "postgresql://app:app@localhost:5432/practice")
    if not dsn:
        raise RuntimeError("POSTGRES_DSN environment variable must be set.")

    # Initialize persistence store (Postgres) using same DSN as checkpointer
    app.state.pending_store = PostgresPendingTicketStore(dsn)

    # Use PostgresSaver as a context manager once for the app lifetime
    with PostgresSaver.from_conn_string(dsn) as checkpointer:
        checkpointer.setup()

        # Compile graphs with this single checkpointer instance
        app.state.checkpointer = checkpointer
        app.state.triage_graph = create_triage_graph(checkpointer=checkpointer)
        app.state.admin_review_graph = create_admin_review_graph(checkpointer=checkpointer)

        yield


# Try to import Langfuse for tracing (use langchain integration for run trees)
try:
    from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler  # pyright: ignore[reportMissingImports]
    from langfuse import get_client as get_langfuse_client
    LANGFUSE_AVAILABLE = True
except ImportError:
    try:
        from langfuse import Langfuse, get_client as get_langfuse_client
        LANGFUSE_AVAILABLE = True
        LangfuseCallbackHandler = None
    except ImportError:
        LANGFUSE_AVAILABLE = False
        LangfuseCallbackHandler = None
        Langfuse = None
        get_langfuse_client = None

app = FastAPI(
    title="Ticket Triage System - Phase 1",
    description="Multi-agent LangGraph workflow with customer, assistant, and admin entities",
    version="1.0.0",
    lifespan=lifespan,
)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MOCK_DIR = os.path.join(ROOT, "mock_data")

# Langfuse configuration from environment variables
langfuse_public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
langfuse_secret_key = os.getenv("LANGFUSE_SECRET_KEY")
langfuse_host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
langfuse_project_name = os.getenv("LANGFUSE_PROJECT_NAME", "p1-seafoam-cicada")
langfuse_environment = os.getenv("LANGFUSE_ENVIRONMENT", "development")

# Initialize Langfuse client if available
langfuse_client = None
if LANGFUSE_AVAILABLE and langfuse_public_key and langfuse_secret_key:
    try:
        if Langfuse:
            langfuse_client = Langfuse(
                public_key=langfuse_public_key,
                secret_key=langfuse_secret_key,
                host=langfuse_host
            )
        print(f"[OK] Langfuse tracing enabled (project: {langfuse_project_name}, environment: {langfuse_environment})")
    except Exception as e:
        print(f"[WARN] Langfuse initialization failed: {e}")
        langfuse_client = None
elif not LANGFUSE_AVAILABLE:
    print("[INFO] Langfuse module not installed. Continuing without tracing.")
else:
    print("[INFO] Langfuse keys not configured. Continuing without tracing.")


def get_langfuse_callback(trace_name: str, tags: Optional[list] = None):
    """Create a Langfuse callback handler for run trees and tracing if available."""
    if not LANGFUSE_AVAILABLE or not langfuse_public_key or not langfuse_secret_key:
        return None

    if LangfuseCallbackHandler:
        try:
            return LangfuseCallbackHandler(
                public_key=langfuse_public_key,
                secret_key=langfuse_secret_key,
                host=langfuse_host,
                trace_name=trace_name,
                tags=tags or [langfuse_environment, "triage", "langgraph"],
            )
        except Exception as e:
            print(f"[WARN] Failed to create Langfuse callback: {e}")
    return None


def load(name):
    """Load a JSON file from the mock_data directory."""
    file_path = os.path.join(MOCK_DIR, name)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Required data file not found: {name}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {name}: {str(e)}")


try:
    ORDERS = load("orders.json")
    ISSUES = load("issues.json")
    REPLIES = load("replies.json")
except Exception as e:
    raise RuntimeError(f"Failed to load required data files: {str(e)}")


# Default in-memory storage for pending tickets (overridden in lifespan and in tests)
pending_tickets_store: InMemoryPendingTicketStore | PostgresPendingTicketStore = InMemoryPendingTicketStore()


# Request/Response Models
class TriageInput(BaseModel):
    """Customer ticket submission."""
    ticket_text: str
    order_id: Optional[str] = None


class AdminReviewInput(BaseModel):
    """Admin review decision."""
    ticket_id: str
    decision: str  # "approve" or "reject"
    feedback: Optional[str] = None


class TriageResponse(BaseModel):
    """Response for triage operations."""
    ticket_id: str
    order_id: Optional[str]
    issue_type: Optional[str]
    recommendation: Optional[str]
    status: str
    order: Optional[dict] = None
    message: Optional[str] = None
    policy_citations: Optional[list] = None


@app.get("/health")
def health():
    """Health check endpoint to verify API is running."""
    return {"status": "ok", "langfuse_enabled": langfuse_client is not None}


@app.get("/orders/get")
def orders_get(order_id: str = Query(...)):
    """Get order details by order ID."""
    for o in ORDERS:
        if o["order_id"] == order_id:
            return o
    raise HTTPException(status_code=404, detail="Order not found")


@app.get("/orders/search")
def orders_search(customer_email: Optional[str] = None, q: Optional[str] = None):
    """Search orders by customer email or query string."""
    matches = []
    for o in ORDERS:
        if customer_email and o["email"].lower() == customer_email.lower():
            matches.append(o)
        elif q and (o["order_id"].lower() in q.lower() or o["customer_name"].lower() in q.lower()):
            matches.append(o)
    return {"results": matches}


@app.post("/classify/issue")
def classify_issue(payload: dict):
    """Classify an issue type based on ticket text keywords."""
    text = payload.get("ticket_text", "").lower()
    for rule in ISSUES:
        if rule["keyword"] in text:
            return {"issue_type": rule["issue_type"], "confidence": 0.85}
    return {"issue_type": "unknown", "confidence": 0.1}


def render_reply(issue_type: str, order):
    """Render a reply template by replacing placeholders with order data."""
    template = next((r["template"] for r in REPLIES if r["issue_type"] == issue_type), None)
    if not template:
        template = "Hi {{customer_name}}, we are reviewing order {{order_id}}."
    return template.replace("{{customer_name}}", order.get("customer_name", "Customer")).replace("{{order_id}}", order.get("order_id", ""))


@app.post("/reply/draft")
def reply_draft(payload: dict):
    """Draft a reply based on issue type and order data."""
    return {"reply_text": render_reply(payload.get("issue_type"), payload.get("order", {}))}


@app.post("/triage/invoke", response_model=TriageResponse)
def triage_invoke(body: TriageInput):
    """
    CUSTOMER ENDPOINT: Submit a support ticket for triage.
    
    This initiates the three-entity workflow:
    1. Customer submits ticket (this endpoint)
    2. Assistant processes and drafts recommendation
    3. Returns with status 'awaiting_admin' for admin review
    
    The response includes a ticket_id to use for admin review.
    """
    try:
        if not body.ticket_text or not body.ticket_text.strip():
            raise HTTPException(status_code=400, detail="ticket_text cannot be empty")
        
        # Generate a deterministic ticket ID based on ticket text and optional order_id
        import hashlib
        payload = f"{body.ticket_text}|{body.order_id or ''}"
        ticket_id = hashlib.md5(payload.encode()).hexdigest()[:8]
        
        # Create initial state for LangGraph
        initial_state = {
            "ticket_text": body.ticket_text,
            "order_id": body.order_id,
            "messages": [HumanMessage(content=body.ticket_text)],
            "issue_type": None,
            "evidence": None,
            "recommendation": None,
            "status": None,
            "admin_decision": None,
            "admin_feedback": None
        }
        
        # Prepare config with Langfuse callback for run trees and node metadata
        config = {
            "recursion_limit": 15,
            "configurable": {"thread_id": ticket_id},
            "run_name": f"triage_{ticket_id}",
        }
        callback = get_langfuse_callback(f"triage_{ticket_id}", ["customer", "invoke"])
        if callback:
            config["callbacks"] = [callback]
        
        # Invoke the triage graph (customer -> assistant workflow)
        graph = getattr(app.state, "triage_graph", None)
        if graph is None:
            raise HTTPException(status_code=500, detail="Triage graph is not initialized.")
        final_state = graph.invoke(initial_state, config=config)
        
        # Store the ticket metadata for admin review in persistent store
        store = getattr(app.state, "pending_store", pending_tickets_store)
        store.upsert(
            PendingTicket(
                ticket_id=ticket_id,
                status=final_state.get("status", "awaiting_admin"),
                issue_type=final_state.get("issue_type"),
                order_id=final_state.get("order_id"),
                recommendation=final_state.get("recommendation"),
            )
        )
        
        # Extract results
        order_id = final_state.get("order_id")
        issue_type = final_state.get("issue_type", "unknown")
        recommendation = final_state.get("recommendation", "")
        status = final_state.get("status", "awaiting_admin")
        evidence = final_state.get("evidence") or {}
        order = evidence.get("order")
        
        return TriageResponse(
            ticket_id=ticket_id,
            order_id=order_id,
            issue_type=issue_type,
            recommendation=recommendation,
            status=status,
            order=order,
            message=f"Ticket processed by assistant. Awaiting admin review at POST /triage/review",
            policy_citations=evidence.get("policy_citations"),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing triage request: {str(e)}")


@app.post("/triage/review", response_model=TriageResponse)
def triage_review(body: AdminReviewInput):
    """
    ADMIN ENDPOINT: Review and approve/reject an assistant's recommendation.
    
    This completes the three-entity workflow:
    1. Admin provides decision (approve/reject)
    2. Updates the ticket status
    3. Returns the final state
    """
    try:
        # Validate decision
        if body.decision.lower() not in ["approve", "reject"]:
            raise HTTPException(
                status_code=400, 
                detail="decision must be 'approve' or 'reject'"
            )
        
        # Get the pending ticket from the persistent store
        store = getattr(app.state, "pending_store", pending_tickets_store)
        pending = store.get(body.ticket_id)
        if pending is None:
            raise HTTPException(
                status_code=404, 
                detail=f"Ticket {body.ticket_id} not found. It may have already been reviewed or expired."
            )
        
        # Load the latest state from the checkpointer using thread_id=ticket_id
        triage = getattr(app.state, "triage_graph", None)
        if triage is None:
            raise HTTPException(status_code=500, detail="Triage graph is not initialized.")
        try:
            snapshot = triage.get_state(config={"configurable": {"thread_id": body.ticket_id}})
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to load ticket state: {str(e)}")

        if snapshot is None:
            raise HTTPException(
                status_code=404,
                detail=f"Ticket state for {body.ticket_id} not found in checkpointer.",
            )

        # Convert StateSnapshot to a mutable dict of values
        stored_state = dict(getattr(snapshot, "values", snapshot))

        # Add admin decision to state
        stored_state["admin_decision"] = body.decision.lower()
        stored_state["admin_feedback"] = body.feedback
        
        # Prepare config with Langfuse callback for run trees
        config = {
            "recursion_limit": 10,
            "configurable": {"thread_id": body.ticket_id},
            "run_name": f"admin_review_{body.ticket_id}",
        }
        callback = get_langfuse_callback(f"admin_review_{body.ticket_id}", ["admin", "review"])
        if callback:
            config["callbacks"] = [callback]
        
        triage_status = stored_state.get("status")

        # For refund tickets in awaiting_approval, resume the main triage graph.
        if triage_status == "awaiting_approval":
            # Resume the interrupted triage graph so that commit_refund runs.
            final_state = triage.invoke(
                Command(resume=body.decision.lower()),
                config=config,
            )
            store.delete(body.ticket_id)
        else:
            # Fallback to existing admin review graph for non-refund flows.
            graph = getattr(app.state, "admin_review_graph", None)
            if graph is None:
                raise HTTPException(status_code=500, detail="Admin review graph is not initialized.")
            final_state = graph.invoke(stored_state, config=config)
            store.delete(body.ticket_id)
        
        # Extract results
        evidence = final_state.get("evidence") or {}
        verb = "approved" if body.decision.lower() == "approve" else "rejected"
        
        return TriageResponse(
            ticket_id=body.ticket_id,
            order_id=final_state.get("order_id"),
            issue_type=final_state.get("issue_type"),
            recommendation=final_state.get("recommendation"),
            status=final_state.get("status", "completed"),
            order=evidence.get("order"),
            message=f"Ticket {verb} by admin.{f' Feedback: {body.feedback}' if body.feedback else ''}",
            policy_citations=evidence.get("policy_citations"),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing admin review: {str(e)}")


@app.get("/triage/pending")
def get_pending_tickets():
    """
    ADMIN ENDPOINT: List all tickets awaiting admin review.
    """
    store = getattr(app.state, "pending_store", pending_tickets_store)
    tickets = store.list_pending()
    pending_list = []
    for ticket in tickets.values():
        pending_list.append(
            {
                "ticket_id": ticket.ticket_id,
                "order_id": ticket.order_id,
                "issue_type": ticket.issue_type,
                "recommendation": ticket.recommendation,
                "status": ticket.status,
            }
        )
    return {"pending_tickets": pending_list, "count": len(pending_list)}

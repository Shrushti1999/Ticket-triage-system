"""
FastAPI application for Ticket Triage System.

Three-entity workflow:
- Customer: POST /triage/invoke - Submit a support ticket
- Assistant: Automatically processes and drafts recommendation
- Admin: POST /triage/review - Approve or reject the recommendation
"""
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
import json
import os
from typing import Optional
from langchain_core.messages import HumanMessage
from app.graph import triage_graph, admin_review_graph

# Try to import Langfuse for tracing
try:
    from langfuse.callback import CallbackHandler as LangfuseCallbackHandler  # pyright: ignore[reportMissingImports]
    LANGFUSE_AVAILABLE = True
except ImportError:
    try:
        from langfuse import Langfuse
        # Create a wrapper for basic tracing without callback handler
        LANGFUSE_AVAILABLE = True
        LangfuseCallbackHandler = None
    except ImportError:
        LANGFUSE_AVAILABLE = False
        LangfuseCallbackHandler = None
        Langfuse = None

app = FastAPI(
    title="Ticket Triage System - Phase 1",
    description="Multi-agent LangGraph workflow with customer, assistant, and admin entities",
    version="1.0.0"
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
    """Create a Langfuse callback handler for tracing if available."""
    if not LANGFUSE_AVAILABLE or not langfuse_public_key or not langfuse_secret_key:
        return None
    
    if LangfuseCallbackHandler:
        try:
            return LangfuseCallbackHandler(
                public_key=langfuse_public_key,
                secret_key=langfuse_secret_key,
                host=langfuse_host,
                trace_name=trace_name,
                tags=tags or [langfuse_environment, "triage", "langgraph"]
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


# In-memory storage for pending tickets (in production, use a database)
pending_tickets = {}


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
        
        # Generate a simple ticket ID
        import hashlib
        import time
        ticket_id = hashlib.md5(f"{body.ticket_text}{time.time()}".encode()).hexdigest()[:8]
        
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
        
        # Prepare config with Langfuse callback if available
        config = {"recursion_limit": 15}
        callback = get_langfuse_callback(f"triage_{ticket_id}", ["customer", "invoke"])
        if callback:
            config["callbacks"] = [callback]
        
        # Invoke the triage graph (customer -> assistant workflow)
        final_state = triage_graph.invoke(initial_state, config=config)
        
        # Store the state for admin review
        pending_tickets[ticket_id] = final_state
        
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
            message=f"Ticket processed by assistant. Awaiting admin review at POST /triage/review"
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
        
        # Get the pending ticket
        if body.ticket_id not in pending_tickets:
            raise HTTPException(
                status_code=404, 
                detail=f"Ticket {body.ticket_id} not found. It may have already been reviewed or expired."
            )
        
        # Get the stored state
        stored_state = pending_tickets[body.ticket_id]
        
        # Add admin decision to state
        stored_state["admin_decision"] = body.decision.lower()
        stored_state["admin_feedback"] = body.feedback
        
        # Prepare config with Langfuse callback if available
        config = {"recursion_limit": 10}
        callback = get_langfuse_callback(f"admin_review_{body.ticket_id}", ["admin", "review"])
        if callback:
            config["callbacks"] = [callback]
        
        # Invoke the admin review graph
        final_state = admin_review_graph.invoke(stored_state, config=config)
        
        # Remove from pending (completed)
        del pending_tickets[body.ticket_id]
        
        # Extract results
        evidence = final_state.get("evidence") or {}
        
        return TriageResponse(
            ticket_id=body.ticket_id,
            order_id=final_state.get("order_id"),
            issue_type=final_state.get("issue_type"),
            recommendation=final_state.get("recommendation"),
            status=final_state.get("status", "completed"),
            order=evidence.get("order"),
            message=f"Ticket {body.decision}d by admin.{f' Feedback: {body.feedback}' if body.feedback else ''}"
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
    pending_list = []
    for ticket_id, state in pending_tickets.items():
        pending_list.append({
            "ticket_id": ticket_id,
            "order_id": state.get("order_id"),
            "issue_type": state.get("issue_type"),
            "recommendation": state.get("recommendation"),
            "status": state.get("status")
        })
    return {"pending_tickets": pending_list, "count": len(pending_list)}

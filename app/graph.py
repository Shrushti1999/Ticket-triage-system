"""
Defines the LangGraph structure for the application.

Three-entity workflow:
- Customer: Submits ticket via /triage/invoke
- Assistant: Processes ticket (ingest -> classify -> fetch_order -> draft_reply)
- Admin: Reviews and approves/rejects via /triage/review
"""
import json
import logging
import os
import re
from typing import Literal
from app.state import GraphState
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, ToolCall
from langgraph.prebuilt import ToolNode
from langgraph.graph import StateGraph, END
from langgraph.types import interrupt
from app.tools import fetch_order, tools
from app import payments
from app.policy_vector_store import query_policies

# Optional: Langfuse context for updating node metadata in run trees
try:  # pragma: no cover - optional observability integration
    from langfuse.decorators import langfuse_context  # type: ignore[import]
except Exception:  # pragma: no cover
    langfuse_context = None

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load issues classification rules (same logic as app/main.py)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MOCK_DIR = os.path.join(ROOT, "mock_data")


def _load_issues():
    """Load issues classification rules from mock_data/issues.json"""
    with open(os.path.join(MOCK_DIR, "issues.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def _load_replies():
    """Load reply templates from mock_data/replies.json"""
    with open(os.path.join(MOCK_DIR, "replies.json"), "r", encoding="utf-8") as f:
        return json.load(f)


# Create ToolNode for executing tools (as per requirements)
tool_node = ToolNode(tools)


def ingest(state: GraphState) -> GraphState:
    """
    Initial node that extracts and normalizes initial data from the input.
    Called when CUSTOMER submits a ticket.
    
    Extracts ticket_text from state (either directly or from the last user message)
    and extracts order_id using regex if not already present in state.
    
    Args:
        state: The current graph state.
        
    Returns:
        Updated state with ticket_text and order_id populated.
    """
    # Extract ticket_text - check if it's directly in state first
    ticket_text = state.get("ticket_text", "")
    
    # If ticket_text is not in state or empty, extract from the last user message
    if not ticket_text and state.get("messages"):
        messages = state["messages"]
        # Find the last user message (from customer)
        for message in reversed(messages):
            if isinstance(message, HumanMessage):
                ticket_text = message.content if hasattr(message, "content") else str(message)
                break
    
    # Extract order_id if not already present in state
    order_id = state.get("order_id")
    
    # If order_id is missing, try to extract it from ticket_text using regex
    if not order_id and ticket_text:
        pattern = r"ORD\d{4}"
        match = re.search(pattern, ticket_text, re.IGNORECASE)
        if match:
            order_id = match.group().upper()  # Normalize to uppercase
    
    # Return updated state with status set to pending
    updated_state = {
        **state, 
        "ticket_text": ticket_text, 
        "order_id": order_id,
        "status": "pending"
    }
    
    logger.info(f"Ingest complete: order_id={order_id}, status=pending")
    return updated_state


def classify_issue(state: GraphState) -> GraphState:
    """
    ASSISTANT node: Classifies the issue type based on keywords in the ticket text.
    
    Reads ticket_text from state and matches against keyword rules in issues.json.
    Stores the issue_type and confidence in state.
    
    Args:
        state: The current graph state.
        
    Returns:
        Updated state with issue_type and confidence populated.
    """
    # Read ticket_text from state
    ticket_text = state.get("ticket_text", "")
    text_lower = ticket_text.lower()
    
    # Load issues classification rules
    issues_rules = _load_issues()
    
    # Classify by checking keywords in ticket_text
    issue_type = "unknown"
    confidence = 0.1
    
    for rule in issues_rules:
        if rule["keyword"] in text_lower:
            issue_type = rule["issue_type"]
            confidence = 0.85
            break
    
    # Get existing evidence or create new dict
    evidence = state.get("evidence") or {}
    evidence["classification_confidence"] = confidence
    
    # Return updated state
    updated_state = {
        **state,
        "issue_type": issue_type,
        "evidence": evidence
    }
    
    logger.info(f"Issue classified: {issue_type} (confidence: {confidence})")
    return updated_state


def kb_orchestrator(state: GraphState) -> GraphState:
    """
    ASSISTANT node: Retrieve relevant policy chunks and attach citations.

    Builds a simple query string from issue_type and ticket_text, queries the
    policy KB, and populates policy_evidence and policy_citations in state.
    """
    issue_type = state.get("issue_type") or ""
    ticket_text = state.get("ticket_text") or ""

    # Simple, deterministic query construction
    query_parts = []
    if issue_type:
        query_parts.append(str(issue_type))
    if ticket_text:
        query_parts.append(str(ticket_text))
    query_text = " - ".join(query_parts).strip()

    if not query_text:
        return state

    try:
        matches = query_policies(query_text, k=3)
    except Exception as exc:
        logger.error(f"kb_orchestrator retrieval failed: {exc}")
        return state

    citations = sorted({m["file_name"] for m in matches}) if matches else []

    # Extract stable document identifiers for observability
    retrieved_ids = [
        str(m.get("id"))
        for m in matches
        if m.get("id") is not None
    ]

    # Attach retrieval metadata to the current Langfuse node, if available
    if langfuse_context is not None and retrieved_ids:
        try:
            langfuse_context.update_current_observation(
                metadata={
                    "retrieved_doc_ids": json.dumps(retrieved_ids),
                    "retrieval_query": query_text,
                }
            )
        except Exception as exc:  # pragma: no cover - observability must not break core flow
            logger.warning(f"Failed to update Langfuse retrieval metadata: {exc}")

    updated_state = {
        **state,
        "policy_evidence": matches,
        "policy_citations": citations,
    }

    logger.info(
        "kb_orchestrator retrieved %d policies, citations=%s",
        len(matches),
        ",".join(citations) if citations else "none",
    )
    return updated_state


def prepare_tool_call(state: GraphState) -> GraphState:
    """
    ASSISTANT node: Prepares an AIMessage with a tool call for fetch_order.
    This enables using ToolNode as required.
    
    Args:
        state: The current graph state containing order_id.
        
    Returns:
        Updated state with AIMessage containing tool call.
    """
    order_id = state.get("order_id")
    messages = list(state.get("messages", []))
    
    if order_id:
        # Create a tool call for fetch_order
        tool_call = ToolCall(
            name="fetch_order",
            args={"order_id": order_id},
            id=f"call_{order_id}"
        )
        
        # Create AIMessage with the tool call (simulating assistant deciding to fetch order)
        ai_message = AIMessage(
            content=f"I'll fetch the order details for {order_id}.",
            tool_calls=[tool_call]
        )
        messages.append(ai_message)
        logger.info(f"Prepared tool call for order_id: {order_id}")
    
    return {**state, "messages": messages}


def process_tool_result(state: GraphState) -> GraphState:
    """
    ASSISTANT node: Processes the result from ToolNode and stores in evidence.
    
    Args:
        state: The current graph state with tool results in messages.
        
    Returns:
        Updated state with order data in evidence.
    """
    messages = state.get("messages", [])
    evidence = state.get("evidence") or {}
    
    # Find the last ToolMessage
    for message in reversed(messages):
        if isinstance(message, ToolMessage):
            try:
                # Parse the tool result
                content = message.content
                if isinstance(content, str):
                    order_data = json.loads(content)
                else:
                    order_data = content
                    
                evidence["order"] = order_data
                logger.info(f"Processed tool result for order: {order_data.get('order_id', 'unknown')}")
            except (json.JSONDecodeError, TypeError) as e:
                logger.error(f"Failed to parse tool result: {e}")
                evidence["order_error"] = str(e)
            break
    
    return {**state, "evidence": evidence}


def draft_reply(state: GraphState) -> GraphState:
    """
    ASSISTANT node: Drafts a reply recommendation based on issue type and order data.
    After drafting, sets status to 'awaiting_admin' for admin review.
    
    Args:
        state: The current graph state containing issue_type and order data.
        
    Returns:
        Updated state with recommendation and awaiting_admin status.
    """
    try:
        # Load reply templates
        replies = _load_replies()
        
        # Get issue_type from state
        issue_type = state.get("issue_type", "unknown")
        
        # Get order data from evidence
        evidence = state.get("evidence") or {}
        order = evidence.get("order", {})
        
        # Find matching reply template from replies.json
        template = next(
            (r["template"] for r in replies if r["issue_type"] == issue_type),
            None
        )
        
        # Handle case where template is not found (use default template)
        if not template:
            template = "Hi {{customer_name}}, we are reviewing order {{order_id}}."
        
        # Replace placeholders with actual values
        # Safely handle None values
        customer_name = order.get("customer_name") or "Customer"
        order_id = order.get("order_id") or state.get("order_id")
        
        # Check if order_id is None or missing - generate fallback reply
        if not order_id:
            reply_text = "Could you please provide your order ID so I can assist you further?"
        else:
            # Ensure customer_name and order_id are strings for replace()
            customer_name = str(customer_name)
            order_id = str(order_id)
            
            # Replace placeholders in template with actual values
            reply_text = template.replace("{{customer_name}}", customer_name).replace(
                "{{order_id}}", order_id
            )
        
        # Add AIMessage showing assistant's recommendation
        messages = list(state.get("messages", []))
        messages.append(AIMessage(
            content=f"[ASSISTANT RECOMMENDATION]\nIssue Type: {issue_type}\nDraft Reply: {reply_text}\n\nAwaiting admin review..."
        ))
        
        # Return updated state with recommendation and awaiting_admin status
        updated_state = {
            **state,
            "recommendation": reply_text,
            "evidence": evidence,
            "messages": messages,
            "status": "awaiting_admin"  # Now waiting for admin to review
        }
        
        logger.info(f"Reply drafted, status set to awaiting_admin for issue_type: {issue_type}")
        return updated_state
    except Exception as e:
        logger.error(f"Error drafting reply: {str(e)}")
        return {
            **state,
            "recommendation": f"Error drafting reply: {str(e)}",
            "status": "awaiting_admin"
        }


def propose_remedy(state: GraphState) -> GraphState:
    """
    ASSISTANT node: Propose a refund remedy and pause for admin approval.

    Responsibilities:
    1) Call payments.refund_preview(order_id) and store in state.refund_preview
    2) Set state.status = "awaiting_approval"
    3) Pause graph execution via LangGraph interrupt (human-in-the-loop)
    """
    order_id = state.get("order_id")
    preview = payments.refund_preview(order_id)

    messages = list(state.get("messages", []))
    messages.append(
        AIMessage(
            content="[APPROVAL REQUIRED]\nA refund preview has been prepared and requires admin approval."
        )
    )

    return {
        **state,
        "refund_preview": preview,
        "status": "awaiting_approval",
        "messages": messages,
    }


def policy_evaluator(state: GraphState) -> GraphState:
    """
    ASSISTANT node: Validate refund-like actions against retrieved policies and enforce citations.

    Assumes refund_preview (for monetary actions) and policy_evidence / policy_citations
    have been populated by previous nodes.
    """
    policy_evidence = state.get("policy_evidence") or []
    policy_citations = state.get("policy_citations") or []
    recommendation = state.get("recommendation")
    refund_preview = state.get("refund_preview")
    messages = list(state.get("messages", []))

    if not policy_evidence:
        # Simple behavior: keep the recommendation but surface that no policy was found.
        messages.append(
            AIMessage(
                content="[POLICY CHECK] No matching policy was found for this action. "
                "Admin should review carefully."
            )
        )
        return {
            **state,
            "messages": messages,
            "policy_citations": [],
        }

    # Ensure citations are present and consistent with evidence.
    filenames = sorted({str(item.get("file_name", "")) for item in policy_evidence if item.get("file_name")})
    if filenames:
        policy_citations = filenames

    citation_str = ""
    if policy_citations:
        joined = ", ".join(policy_citations)
        citation_str = f" (see {joined})"

    # Optionally, minimally adjust recommendation text to append citations.
    if recommendation and citation_str and citation_str not in recommendation:
        recommendation = recommendation + citation_str

    # Build citation span metadata for Langfuse run trees
    citation_spans = []
    if recommendation and citation_str:
        try:
            start = max(0, len(recommendation) - len(citation_str))
            end = len(recommendation)
            citation_spans.append(
                {
                    "start": start,
                    "end": end,
                    "text": recommendation[start:end],
                    "documents": list(policy_citations),
                }
            )
        except Exception as exc:  # pragma: no cover
            logger.warning(f"Failed to construct citation spans: {exc}")

    # Attach answer-level citation metadata to the current Langfuse node
    if langfuse_context is not None and citation_spans:
        try:
            langfuse_context.update_current_observation(
                metadata={
                    "policy_citations": policy_citations,
                    "citation_spans": citation_spans,
                }
            )
        except Exception as exc:  # pragma: no cover
            logger.warning(f"Failed to update Langfuse citation metadata: {exc}")

    # Also attach citations into refund_preview metadata if present.
    if isinstance(refund_preview, dict) and policy_citations:
        updated_preview = dict(refund_preview)
        updated_preview["policy_citations"] = policy_citations
        refund_preview = updated_preview

    messages.append(
        AIMessage(
            content="[POLICY CHECK] Proposed action is backed by policies: "
            + ", ".join(policy_citations)
            if policy_citations
            else "[POLICY CHECK] Policy evidence attached."
        )
    )

    return {
        **state,
        "recommendation": recommendation,
        "refund_preview": refund_preview,
        "policy_citations": policy_citations,
        "messages": messages,
    }


def wait_for_admin_approval(state: GraphState) -> GraphState:
    """
    Pause graph execution until an admin approves/rejects.

    This node intentionally interrupts (human-in-the-loop). Because `interrupt()`
    raises before the node can return, any state that must be checkpointed prior
    to waiting (like `refund_preview` and `status`) should be set in the
    preceding node (`propose_remedy`).
    """
    resume_value = interrupt(
        {
            "type": "admin_approval",
            "status": state.get("status"),
            "order_id": state.get("order_id"),
            "refund_preview": state.get("refund_preview"),
        }
    )

    if isinstance(resume_value, dict):
        return {
            **state,
            "admin_decision": (resume_value.get("decision") or "").lower() or state.get("admin_decision"),
            "admin_feedback": resume_value.get("feedback"),
        }

    if isinstance(resume_value, str):
        return {**state, "admin_decision": resume_value.lower()}

    return state


def admin_review(state: GraphState) -> GraphState:
    """
    ADMIN node: Processes admin decision on the recommendation.
    
    This node is called after admin provides their decision via /triage/review endpoint.
    Updates the status based on admin_decision.
    
    Args:
        state: The current graph state with admin_decision.
        
    Returns:
        Updated state with final status (approved/rejected/completed).
    """
    admin_decision = state.get("admin_decision", "").lower()
    admin_feedback = state.get("admin_feedback", "")
    messages = list(state.get("messages", []))
    
    if admin_decision == "approve":
        status = "approved"
        messages.append(AIMessage(
            content=f"[ADMIN APPROVED]\nThe recommendation has been approved.{f' Feedback: {admin_feedback}' if admin_feedback else ''}"
        ))
        logger.info("Admin approved the recommendation")
    elif admin_decision == "reject":
        status = "rejected"
        messages.append(AIMessage(
            content=f"[ADMIN REJECTED]\nThe recommendation has been rejected.{f' Reason: {admin_feedback}' if admin_feedback else ''}"
        ))
        logger.info(f"Admin rejected the recommendation. Feedback: {admin_feedback}")
    else:
        # No decision yet, keep awaiting
        status = state.get("status", "awaiting_admin")
        logger.warning(f"No valid admin decision provided: {admin_decision}")
    
    return {
        **state,
        "status": status,
        "messages": messages
    }


def finalize(state: GraphState) -> GraphState:
    """
    Final node: Marks the workflow as completed.
    
    Args:
        state: The current graph state.
        
    Returns:
        Updated state with completed status.
    """
    messages = list(state.get("messages", []))
    admin_decision = (state.get("admin_decision") or "").lower()
    
    if admin_decision == "approve":
        messages.append(AIMessage(content="[WORKFLOW COMPLETE] Reply sent to customer."))
    elif admin_decision == "reject":
        messages.append(AIMessage(content="[WORKFLOW COMPLETE] Reply rejected. Customer ticket requires manual review."))
    
    return {
        **state,
        "status": "completed",
        "messages": messages
    }


def should_fetch_order(state: GraphState) -> Literal["prepare_tool_call", "draft_reply"]:
    """
    Conditional routing function that determines if order should be fetched.
    
    Routes to 'prepare_tool_call' if order_id exists, otherwise skips to 'draft_reply'.
    
    Args:
        state: The current graph state.
        
    Returns:
        'prepare_tool_call' if order_id exists, 'draft_reply' otherwise.
    """
    order_id = state.get("order_id")
    if order_id:
        logger.info(f"Order ID found: {order_id}, routing to fetch_order")
        return "prepare_tool_call"
    else:
        logger.warning("Order ID missing, skipping to draft_reply")
        return "draft_reply"


def route_after_classify(state: GraphState) -> Literal["kb_orchestrator", "prepare_tool_call", "draft_reply"]:
    """
    Conditional routing after classification.

    - Refund requests go to kb_orchestrator (KB retrieval) before propose_remedy.
    - Otherwise, continue down the existing fetch-order / draft-reply path.
    """
    if state.get("issue_type") == "refund_request":
        return "kb_orchestrator"
    return should_fetch_order(state)


def route_after_admin_review(state: GraphState) -> Literal["commit_refund", "finalize"]:
    """
    Route after admin_review:
    - For approved refund requests, run commit_refund.
    - Otherwise, go directly to finalize.
    """
    if state.get("issue_type") == "refund_request" and (state.get("admin_decision") or "").lower() == "approve":
        return "commit_refund"
    return "finalize"


def commit_refund(state: GraphState) -> GraphState:
    """
    COMMIT node: Commit the refund after admin approval.

    Responsibilities:
    1) Read approval decision from state.
    2) If approved, call payments.refund_commit(order_id).
    3) Set state.status = "completed".
    """
    order_id = state.get("order_id")
    admin_decision = (state.get("admin_decision") or "").lower()
    messages = list(state.get("messages", []))
    evidence = state.get("evidence") or {}

    if admin_decision == "approve" and order_id:
        result = payments.refund_commit(order_id)
        evidence["refund_commit"] = result
        messages.append(
            AIMessage(
                content=f"[REFUND COMMITTED]\nRefund has been committed for order {order_id}."
            )
        )
        return {
            **state,
            "status": "completed",
            "evidence": evidence,
            "messages": messages,
        }

    # Not approved or missing order_id; nothing to commit.
    return {**state, "messages": messages}


# Create the LangGraph workflow
def create_triage_graph(checkpointer=None):
    """
    Creates and compiles the LangGraph workflow for ticket triage.
    
    Implements three-entity workflow:
    1. Customer submits ticket -> ingest
    2. Assistant processes -> classify_issue -> fetch_order (ToolNode) -> draft_reply
    3. Admin reviews -> admin_review -> finalize
    
    Args:
        checkpointer: Optional checkpointer (e.g. PostgresSaver) for persistence.
    
    Returns:
        Compiled LangGraph workflow.
    """
    try:
        # Initialize StateGraph with GraphState
        workflow = StateGraph(GraphState)
        
        # Add nodes for the three-entity workflow
        # Customer entry point
        workflow.add_node("ingest", ingest)
        
        # Assistant nodes
        workflow.add_node("classify_issue", classify_issue)
        workflow.add_node("kb_orchestrator", kb_orchestrator)
        workflow.add_node("prepare_tool_call", prepare_tool_call)
        workflow.add_node("fetch_order", tool_node)  # Using ToolNode as required
        workflow.add_node("process_tool_result", process_tool_result)
        workflow.add_node("draft_reply", draft_reply)
        workflow.add_node("propose_remedy", propose_remedy)
        workflow.add_node("policy_evaluator", policy_evaluator)
        workflow.add_node("wait_for_admin_approval", wait_for_admin_approval)
        
        # Admin nodes
        workflow.add_node("admin_review", admin_review)
        workflow.add_node("commit_refund", commit_refund)
        workflow.add_node("finalize", finalize)
        
        # Add edges
        # START -> ingest (Customer submits ticket)
        workflow.set_entry_point("ingest")
        
        # ingest -> classify_issue (Assistant starts processing)
        workflow.add_edge("ingest", "classify_issue")
        
        # classify_issue -> conditional routing
        workflow.add_conditional_edges(
            "classify_issue",
            route_after_classify,
            {
                "kb_orchestrator": "kb_orchestrator",
                "prepare_tool_call": "prepare_tool_call",
                "draft_reply": "draft_reply",
            }
        )

        # kb_orchestrator -> propose_remedy for refund / monetary flows
        workflow.add_edge("kb_orchestrator", "propose_remedy")
        
        # prepare_tool_call -> fetch_order (ToolNode)
        workflow.add_edge("prepare_tool_call", "fetch_order")
        
        # fetch_order -> process_tool_result
        workflow.add_edge("fetch_order", "process_tool_result")
        
        # process_tool_result -> draft_reply
        workflow.add_edge("process_tool_result", "draft_reply")
        
        # draft_reply -> END (pause for admin review)
        # The graph pauses here, waiting for admin input via /triage/review
        workflow.add_edge("draft_reply", END)

        # propose_remedy -> policy_evaluator -> wait_for_admin_approval -> admin_review
        workflow.add_edge("propose_remedy", "policy_evaluator")
        workflow.add_edge("policy_evaluator", "wait_for_admin_approval")
        workflow.add_edge("wait_for_admin_approval", "admin_review")
        # admin_review -> (commit_refund | finalize)
        workflow.add_conditional_edges(
            "admin_review",
            route_after_admin_review,
            {
                "commit_refund": "commit_refund",
                "finalize": "finalize",
            },
        )
        # commit_refund -> finalize -> END
        workflow.add_edge("commit_refund", "finalize")
        workflow.add_edge("finalize", END)
        
        # Compile the graph (with checkpointer if provided)
        graph = workflow.compile(checkpointer=checkpointer)
        logger.info("Triage graph compiled successfully with three-entity workflow")
        
        return graph
    except Exception as e:
        logger.error(f"Error creating triage graph: {str(e)}")
        raise


def create_admin_review_graph(checkpointer=None):
    """
    Creates a separate graph for admin review workflow.
    This is invoked when admin submits their decision.
    
    Args:
        checkpointer: Optional checkpointer (e.g. PostgresSaver) for persistence.
    
    Returns:
        Compiled LangGraph workflow for admin review.
    """
    try:
        workflow = StateGraph(GraphState)
        
        workflow.add_node("admin_review", admin_review)
        workflow.add_node("finalize", finalize)
        
        workflow.set_entry_point("admin_review")
        workflow.add_edge("admin_review", "finalize")
        workflow.add_edge("finalize", END)
        
        graph = workflow.compile(checkpointer=checkpointer)
        logger.info("Admin review graph compiled successfully")
        
        return graph
    except Exception as e:
        logger.error(f"Error creating admin review graph: {str(e)}")
        raise


# Create and export compiled graphs (tests and fallback)
# Interrupts require a checkpointer to resume correctly, so we provide MemorySaver here.
try:
    from langgraph.checkpoint.memory import MemorySaver

    _memory_saver = MemorySaver()
    if hasattr(_memory_saver, "setup"):
        _memory_saver.setup()
except Exception:
    _memory_saver = None

triage_graph = create_triage_graph(checkpointer=_memory_saver)
admin_review_graph = create_admin_review_graph(checkpointer=_memory_saver)

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
from app.tools import fetch_order, tools

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
    status = state.get("status", "")
    
    if status == "approved":
        messages.append(AIMessage(content="[WORKFLOW COMPLETE] Reply sent to customer."))
    elif status == "rejected":
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


def check_admin_decision(state: GraphState) -> Literal["finalize", "admin_review"]:
    """
    Checks if admin has made a decision.
    
    Args:
        state: The current graph state.
        
    Returns:
        'finalize' if decision made, 'admin_review' otherwise.
    """
    admin_decision = state.get("admin_decision")
    if admin_decision in ["approve", "reject"]:
        return "finalize"
    return "admin_review"


# Create the LangGraph workflow
def create_triage_graph(checkpointer=None):
    """
    Creates and compiles the LangGraph workflow for ticket triage.
    
    Implements three-entity workflow:
    1. Customer submits ticket -> ingest
    2. Assistant processes -> classify_issue -> fetch_order (ToolNode) -> draft_reply
    3. Admin reviews -> admin_review -> finalize
    
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
        workflow.add_node("prepare_tool_call", prepare_tool_call)
        workflow.add_node("fetch_order", tool_node)  # Using ToolNode as required
        workflow.add_node("process_tool_result", process_tool_result)
        workflow.add_node("draft_reply", draft_reply)
        
        # Admin nodes
        workflow.add_node("admin_review", admin_review)
        workflow.add_node("finalize", finalize)
        
        # Add edges
        # START -> ingest (Customer submits ticket)
        workflow.set_entry_point("ingest")
        
        # ingest -> classify_issue (Assistant starts processing)
        workflow.add_edge("ingest", "classify_issue")
        
        # classify_issue -> conditional routing
        workflow.add_conditional_edges(
            "classify_issue",
            should_fetch_order,
            {
                "prepare_tool_call": "prepare_tool_call",
                "draft_reply": "draft_reply"
            }
        )
        
        # prepare_tool_call -> fetch_order (ToolNode)
        workflow.add_edge("prepare_tool_call", "fetch_order")
        
        # fetch_order -> process_tool_result
        workflow.add_edge("fetch_order", "process_tool_result")
        
        # process_tool_result -> draft_reply
        workflow.add_edge("process_tool_result", "draft_reply")
        
        # draft_reply -> END (pause for admin review)
        # The graph pauses here, waiting for admin input via /triage/review
        workflow.add_edge("draft_reply", END)
        
        # Compile the graph
        # Optionally attach a persistent checkpointer (e.g., PostgresSaver)
        if checkpointer is not None:
            graph = workflow.compile(checkpointer=checkpointer)
        else:
            graph = workflow.compile()
        logger.info("Triage graph compiled successfully with three-entity workflow")
        
        return graph
    except Exception as e:
        logger.error(f"Error creating triage graph: {str(e)}")
        raise


def create_admin_review_graph(checkpointer=None):
    """
    Creates a separate graph for admin review workflow.
    This is invoked when admin submits their decision.
    
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
        
        if checkpointer is not None:
            graph = workflow.compile(checkpointer=checkpointer)
        else:
            graph = workflow.compile()
        logger.info("Admin review graph compiled successfully")
        
        return graph
    except Exception as e:
        logger.error(f"Error creating admin review graph: {str(e)}")
        raise


# Create and export the compiled graphs for non-server usage (e.g., tests)
triage_graph = create_triage_graph()
admin_review_graph = create_admin_review_graph()

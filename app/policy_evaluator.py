"""
Policy evaluator node for LangGraph.

Builds a query from the user issue and proposed action, retrieves policy
citations via kb_orchestrator, and writes policy_citations and a short
policy_justification into state["evidence"].

When Langfuse is enabled, logs retrieved document IDs in node metadata
for observability (run tree UI).
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.kb_orchestrator import kb_orchestrator
from app.state import GraphState


def _langfuse_log_retrieved_doc_ids(doc_ids: List[str]) -> None:
    """Log retrieved document IDs on the current Langfuse span (run tree node metadata)."""
    if not doc_ids:
        return
    try:
        from langfuse import get_client
        client = get_client()
        if hasattr(client, "update_current_span"):
            client.update_current_span(metadata={"retrieved_document_ids": doc_ids})
    except Exception:
        pass


def _langfuse_log_citation_spans(citations: List[Dict[str, Any]]) -> None:
    """Record citation spans on the current Langfuse span so they appear in the run tree UI."""
    if not citations:
        return
    # Format for run tree UI: list of {doc_id, file, snippet} (and optional start/end if we had offsets)
    spans = [
        {
            "doc_id": c.get("doc_id"),
            "file": c.get("file"),
            "snippet": (c.get("snippet") or "")[:200],
        }
        for c in citations
    ]
    try:
        from langfuse import get_client
        client = get_client()
        if hasattr(client, "update_current_span"):
            client.update_current_span(metadata={"citation_spans": spans})
    except Exception:
        pass


def _build_query(state: GraphState) -> str:
    """Build a concise query describing the user issue and proposed action."""
    issue_type = state.get("issue_type") or "unknown"
    ticket_text = (state.get("ticket_text") or "").strip()
    recommendation = state.get("recommendation") or ""
    refund_preview = state.get("refund_preview")

    parts: List[str] = []
    parts.append(f"Issue: {issue_type}.")
    if ticket_text:
        parts.append(f"Customer: {ticket_text}")
    if recommendation:
        parts.append(f"Proposed action: {recommendation}")
    if refund_preview and isinstance(refund_preview, dict):
        if "order_id" in refund_preview:
            parts.append(f"Refund preview for order {refund_preview.get('order_id')}.")
        elif "error" not in refund_preview:
            parts.append("Refund preview requested.")

    return " ".join(parts)


def _build_justification(citations: List[Dict[str, Any]]) -> str:
    """Short justification referencing cited policy filenames and why they apply."""
    if not citations:
        return "No policy citations retrieved."
    files = [c.get("file") for c in citations if c.get("file")]
    if not files:
        return "Policy citations retrieved; no filenames available."
    unique = list(dict.fromkeys(files))
    names = ", ".join(unique)
    return f"Cited policies ({names}) are relevant to the issue type and proposed action."


def policy_evaluator(state: GraphState) -> GraphState:
    """
    LangGraph node that wires policy citations into evidence.

    Builds a query from the user issue and proposed action (issue_type,
    ticket_text, recommendation, refund_preview), calls kb_orchestrator
    to get policy_citations, then writes policy_citations and a short
    policy_justification into state["evidence"]. Does not raise if no
    citations are found; policy_citations is set to an empty list.
    """
    evidence = dict(state.get("evidence") or {})

    query_text = _build_query(state)
    # Pass state with our query so kb_orchestrator uses it for retrieval
    try:
        result = kb_orchestrator({**state, "ticket_text": query_text})
        citations = (result.get("evidence") or {}).get("policy_citations") or []
    except Exception:
        citations = []

    evidence["policy_citations"] = citations
    evidence["policy_justification"] = _build_justification(citations)

    # Observability: log retrieved document IDs and citation spans for run tree UI
    doc_ids = [c.get("doc_id") for c in citations if c.get("doc_id") is not None]
    _langfuse_log_retrieved_doc_ids(doc_ids)
    _langfuse_log_citation_spans(citations)

    return {
        **state,
        "evidence": evidence,
    }

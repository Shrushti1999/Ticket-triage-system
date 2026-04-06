from __future__ import annotations

from typing import Any, Dict, Optional


def refund_preview(order_id: Optional[str]) -> Dict[str, Any]:
    """
    Generate a refund preview for an order.

    This project doesn't yet integrate with a real payment processor, so this
    function returns a deterministic preview payload that downstream nodes and
    APIs can persist and present for admin approval.
    """
    if not order_id:
        return {
            "ok": False,
            "reason": "missing_order_id",
            "order_id": order_id,
        }

    return {
        "ok": True,
        "order_id": order_id,
        "action": "refund",
        "amount": None,
        "currency": "USD",
        "requires_admin_approval": True,
    }


def refund_commit(order_id: Optional[str]) -> Dict[str, Any]:
    """
    Commit a refund for an order.

    In this demo implementation we simply return a structured payload instead
    of calling a real payment processor. The graph can store this in state for
    observability or logging.
    """
    if not order_id:
        return {
            "ok": False,
            "reason": "missing_order_id",
            "order_id": order_id,
        }

    return {
        "ok": True,
        "order_id": order_id,
        "action": "refund_commit",
    }

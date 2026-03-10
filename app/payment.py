"""
Payment and refund-related utilities.

This module exposes a small, synchronous API that can be called from the
LangGraph nodes. In particular, it provides ``refund_preview`` which is
used by the graph to propose a remedy for an order.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MOCK_DIR = os.path.join(ROOT, "mock_data")


def _load_orders() -> list[dict[str, Any]]:
    """Load orders from the mock_data directory."""
    orders_path = os.path.join(MOCK_DIR, "orders.json")
    with open(orders_path, "r", encoding="utf-8") as f:
        return json.load(f)


def refund_preview(order_id: str) -> Dict[str, Any]:
    """
    Compute a simple refund preview for the given order.

    For now this uses mock order data and returns:
        - order_id
        - customer_name
        - total_amount as refundable_amount
        - currency
        - original_order (the full order payload)

    Args:
        order_id: The ID of the order to preview a refund for.

    Returns:
        A dictionary containing refund preview information.

    Raises:
        ValueError: If the order cannot be found.
    """
    orders = _load_orders()
    order = next((o for o in orders if o.get("order_id") == order_id), None)
    if order is None:
        raise ValueError(f"Order not found for refund preview: {order_id}")

    return {
        "order_id": order_id,
        "customer_name": order.get("customer_name"),
        "refundable_amount": order.get("total_amount"),
        "currency": order.get("currency", "USD"),
        "original_order": order,
    }


def refund_commit(order_id: str) -> Dict[str, Any]:
    """
    Commit a refund for the given order.

    This is a mock implementation that simulates committing a refund by
    returning a confirmation payload. In a real system this would call a
    payments provider or internal billing service.
    """
    orders = _load_orders()
    order = next((o for o in orders if o.get("order_id") == order_id), None)
    if order is None:
        raise ValueError(f"Order not found for refund commit: {order_id}")

    return {
        "order_id": order_id,
        "refunded_amount": order.get("total_amount"),
        "currency": order.get("currency", "USD"),
        "status": "refunded",
    }

